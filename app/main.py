"""Agent 入口：代码审查助手（命令行交互式）。

这是应用的组合根：创建 OpenAI 客户端、组装会话循环。
未来若改造为 FastAPI 服务，可在此处新增 `app = FastAPI()` 并
把 run_agent 的逻辑迁移为接口处理函数，services 层无需变动。
"""
from app.core.config import get_client, settings
from app.services.context import maybe_compress

# 模块级共享客户端；测试时通过 mock 替换本模块的 client
client = get_client()


def calculate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """按 DeepSeek 官网定价计算一次调用的费用（元）。"""
    prompt_cost = prompt_tokens * settings.PROMPT_PRICE_PER_1K / 1000
    completion_cost = completion_tokens * settings.COMPLETION_PRICE_PER_1K / 1000
    return prompt_cost + completion_cost


def chat_once(messages):
    """调用一次模型，返回 (回复内容, usage)。"""
    response = client.chat.completions.create(
        model=settings.MODEL,
        messages=messages,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
    )
    return response.choices[0].message.content, response.usage


def run_agent():
    """命令行主循环。"""
    print("🤖 代码审查助手已启动，输入 'exit' 退出\n")

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

        reply, usage = chat_once(messages)
        messages.append({"role": "assistant", "content": reply})

        # 取 usage
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        total_tokens = usage.total_tokens

        # 算钱
        turn_cost = calculate_cost(prompt_tokens, completion_tokens)

        # 累计
        total_session_tokens += total_tokens
        total_session_cost += turn_cost

        print(f"\n🤖 助手: {reply}")
        print(f"📊 本轮: 输入 {prompt_tokens} | 输出 {completion_tokens} | 合计 {total_tokens} token")
        print(f"💰 本轮: ¥{turn_cost:.6f} | 会话累计: {total_session_tokens} token, ¥{total_session_cost:.6f}")
        print()


if __name__ == "__main__":
    run_agent()
