"""Agent 入口：代码审查助手（命令行交互式，支持工具调用）。

这是应用的组合根：创建 OpenAI 客户端、组装会话循环。
未来若改造为 FastAPI 服务，可在此处新增 `app = FastAPI()` 并
把 run_agent 的逻辑迁移为接口处理函数，services / tools 层无需变动。

工具调用流程（每个用户回合内）：
  1. 把全部工具声明（registry.schemas()）随消息一起发给模型；
  2. 若模型返回 tool_calls → 依次执行工具，把结果以 role="tool" 消息
     追加回对话，再次调用模型（最多 MAX_TOOL_ROUNDS 轮）；
  3. 若模型直接返回文本 → 该回合结束，展示给用户。
"""
from app.core.config import get_client, settings
from app.services.context import maybe_compress
from app.tools import registry

# 模块级共享客户端；测试时通过 mock 替换本模块的 client
client = get_client()


def calculate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """按 DeepSeek 官网定价计算一次调用的费用（元）。"""
    prompt_cost = prompt_tokens * settings.PROMPT_PRICE_PER_1K / 1000
    completion_cost = completion_tokens * settings.COMPLETION_PRICE_PER_1K / 1000
    return prompt_cost + completion_cost


def chat_once(messages, tools=None):
    """调用一次模型。

    返回 (assistant 消息对象, usage)。消息对象可能携带 tool_calls（模型请求
    调用工具）或 content（最终回复），调用方需自行区分。
    """
    kwargs = {
        "model": settings.MODEL,
        "messages": messages,
        "temperature": settings.TEMPERATURE,
        "max_tokens": settings.MAX_TOKENS,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message, response.usage


def assistant_message_to_dict(message) -> dict:
    """把 SDK 的 assistant 消息对象转成可追加进 messages 列表的字典。

    真实 SDK 消息是 pydantic 模型，用 model_dump 转换；对 mock 对象提供
    兜底转换，保证测试与运行行为一致。
    """
    from pydantic import BaseModel

    if isinstance(message, BaseModel):
        return message.model_dump(exclude_none=True)

    tool_calls = getattr(message, "tool_calls", None) or []
    return {
        "role": "assistant",
        "content": getattr(message, "content", None),
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ],
    }


def run_turn(
    messages,
    tools=None,
    max_rounds=None,
    on_tool_call=None,
    collect_tool_calls=False,
) -> dict:
    """执行一个"用户回合"的「模型 ⇄ 工具」循环，直到模型给出最终回复。

    - messages: 会话消息列表；会被**原地追加**（assistant 工具调用请求、
      tool 结果、最终 assistant 回复），调用方负责管理其生命周期。
    - tools: 工具声明列表；为 None 时使用全局 registry.schemas()。
    - max_rounds: 本回合最多发起几轮工具调用，默认 settings.MAX_TOOL_ROUNDS。
    - on_tool_call: 可选回调 (name, arguments, result)，用于 CLI 打印日志。
    - collect_tool_calls: 为 True 时，返回值里包含本轮全部工具调用记录。

    返回值：
      {
        "reply": 最终文本回复,
        "prompt_tokens": 输入 token,
        "completion_tokens": 输出 token,
        "total_tokens": 本轮总 token,
        "cost": 本轮费用（元）,
        "tool_calls": 工具调用记录列表（仅 collect_tool_calls=True 时非 None）,
      }

    该函数是 CLI 主循环与 API 服务的公共内核：命令行与 Java/HTTP 调用
    走完全相同的工具调用协议，只是「回复展示」与「消息存储」方式不同。
    """
    if tools is None:
        tools = registry.schemas()
    if max_rounds is None:
        max_rounds = settings.MAX_TOOL_ROUNDS

    turn_prompt_tokens = 0
    turn_completion_tokens = 0
    turn_total_tokens = 0
    turn_cost = 0.0
    tool_calls = [] if collect_tool_calls else None
    final_reply = ""

    for _ in range(max_rounds):
        message, usage = chat_once(messages, tools=tools)

        turn_prompt_tokens += usage.prompt_tokens
        turn_completion_tokens += usage.completion_tokens
        turn_total_tokens += usage.total_tokens
        turn_cost += calculate_cost(usage.prompt_tokens, usage.completion_tokens)

        if message.tool_calls:
            # 把模型的工具调用请求追加进对话
            messages.append(assistant_message_to_dict(message))
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                arguments = tool_call.function.arguments
                result = registry.execute(name, arguments)
                if on_tool_call:
                    on_tool_call(name, arguments, result)
                if tool_calls is not None:
                    tool_calls.append({"name": name, "arguments": arguments, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
            continue

        # 模型给出最终文本回复
        final_reply = message.content or ""
        messages.append({"role": "assistant", "content": final_reply})
        break
    else:
        # 达到 max_rounds 仍未给出最终回复，兜底结束本回合
        final_reply = "⚠️ 工具调用轮次达到上限，已中止本次回答。"
        messages.append({"role": "assistant", "content": final_reply})

    return {
        "reply": final_reply,
        "prompt_tokens": turn_prompt_tokens,
        "completion_tokens": turn_completion_tokens,
        "total_tokens": turn_total_tokens,
        "cost": turn_cost,
        "tool_calls": tool_calls,
    }


def _print_tool_call(name: str, arguments: str, result: str) -> None:
    """CLI 模式下展示一次工具调用（供 run_agent 作为 on_tool_call 传入）。"""
    print(f"🔧 调用工具: {name}({arguments})")
    preview = result if len(result) <= 200 else result[:200] + "…"
    print(f"   ↳ {preview}")


def run_agent():
    """命令行主循环。"""
    print("🤖 代码审查助手已启动（支持工具调用：read_file / run_shell / search_code / ask_user）\n")
    print("   输入 'exit' 退出\n")

    messages = [
        {"role": "system", "content": settings.SYSTEM_PROMPT}
    ]

    total_session_tokens = 0
    total_session_cost = 0.0

    while True:
        user_input = input("你: ").strip()

        if user_input.lower() in ("exit", "quit"):
            print(f"\n📋 会话总结:")
            print(f"   总 token: {total_session_tokens}")
            print(f"   总花费: ¥{total_session_cost:.6f}")
            print("👋 再见！")
            break

        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # 上下文窗口限制 + 摘要压缩（超过阈值时自动压缩早期对话）
        messages, _ = maybe_compress(messages)

        # ---- 工具调用循环：模型可能连续多次请求调用工具 ----
        stats = run_turn(messages, on_tool_call=_print_tool_call)
        final_reply = stats["reply"]
        turn_prompt_tokens = stats["prompt_tokens"]
        turn_completion_tokens = stats["completion_tokens"]
        turn_cost = stats["cost"]
        total_session_tokens += stats["total_tokens"]
        total_session_cost += turn_cost

        print(f"\n🤖 助手: {final_reply}")
        print(f"📊 本轮: 输入 {turn_prompt_tokens} | 输出 {turn_completion_tokens} | 合计 {turn_prompt_tokens + turn_completion_tokens} token")
        print(f"💰 本轮: ¥{turn_cost:.6f} | 会话累计: {total_session_tokens} token, ¥{total_session_cost:.6f}")
        print()


if __name__ == "__main__":
    run_agent()
