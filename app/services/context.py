"""摘要压缩与上下文窗口限制。

核心策略（maybe_compress）：
  1. 当前 token 数未超过阈值 → 不做任何事；
  2. 超过阈值 → 把最早的对话（最近 KEEP_RECENT_TURNS 轮除外）调用模型
     压缩成摘要，以一条 system 消息接在系统提示之后；
  3. 若压缩后仍超限（说明最近几轮本身过大），兜底截断最长的单条消息。
"""
import json

from app.core.config import get_client, settings
from app.services.token_utils import count_messages_tokens

# 模块级共享客户端；测试时通过 mock 替换本模块的 client
client = get_client()


def summarize_conversation(messages) -> str:
    """调用模型，把一段较早的对话压缩成中文摘要。"""
    conversation_text = json.dumps(messages, ensure_ascii=False, indent=1)
    summary_messages = [
        {"role": "system", "content": "你是一个对话压缩助手。请把用户提供的对话压缩成一份简洁但信息完整的中文摘要："
                                      "保留所有关键事实、结论、用户需求与未完成的待办事项，不要遗漏重要细节，"
                                      "也不要添加新内容。直接输出摘要正文。"},
        {"role": "user", "content": f"请压缩以下对话：\n{conversation_text}"},
    ]
    response = client.chat.completions.create(
        model=settings.MODEL,
        messages=summary_messages,
        temperature=settings.SUMMARY_TEMPERATURE,
        max_tokens=settings.SUMMARY_MAX_TOKENS,
    )
    return response.choices[0].message.content.strip()


def maybe_compress(messages, verbose=True):
    """上下文窗口限制 + 摘要压缩的核心逻辑。

    返回 (压缩后的消息列表, 压缩前 token 数)。
    """
    limit = settings.MAX_CONTEXT_TOKENS - settings.SAFETY_MARGIN
    before = count_messages_tokens(messages)

    # 未到阈值：直接返回，保持原样
    if before <= int(limit * settings.COMPRESS_THRESHOLD):
        return messages, before

    # 拆分：系统提示 + 可压缩区(older) + 最近保留区(recent)
    head, tail = messages[0], messages[1:]
    keep_count = min(settings.KEEP_RECENT_TURNS * 2, len(tail))
    older, recent = tail[:-keep_count], tail[-keep_count:]

    if older:
        if count_messages_tokens(older) >= settings.MIN_SUMMARIZE_TOKENS:
            summary = summarize_conversation(older)
            messages = [head, {"role": "system", "content": f"【历史对话摘要】\n{summary}"}] + recent
            if verbose:
                print(f"🗜️ 上下文压缩：早期 {len(older)} 条消息已压缩为摘要")
        else:
            # 早期内容太少，不值得调用模型，直接丢弃
            messages = [head] + recent
            if verbose:
                print(f"🗜️ 上下文压缩：早期 {len(older)} 条消息内容过少，已直接丢弃")

    # 兜底：压缩后仍超限 → 反复截断最长的非系统消息（摘要与系统提示不受影响）
    guard = 0
    while count_messages_tokens(messages) > limit and guard < 20:
        guard += 1
        candidates = [(i, m) for i, m in enumerate(messages) if m["role"] != "system"]
        if not candidates:
            break
        idx, longest = max(candidates, key=lambda p: len(p[1].get("content", "")))
        content = longest["content"]
        half = len(content) // 2
        messages[idx] = {**longest, "content": content[:half] + "\n…（内容过长已截断）"}
        if verbose:
            print("⚠️  单条消息过长，已截断一部分")

    if verbose:
        after = count_messages_tokens(messages)
        print(f"📦 上下文占用: {before} → {after} / {settings.MAX_CONTEXT_TOKENS} tokens")
    return messages, before
