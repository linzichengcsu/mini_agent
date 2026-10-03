import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# 系统提示词——定义 Agent 的人设和行为
SYSTEM_PROMPT = """你是一个代码审查助手。
你的职责是帮助开发者发现代码中的潜在问题，并给出改进建议。
用简洁的中文回答，一次只聚焦一个问题。"""

def chat_once(messages):
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.7,
        max_tokens=500
    )

    # 取出 usage
    usage = response.usage
    prompt_tokens = usage.prompt_tokens
    completion_tokens = usage.completion_tokens
    total_tokens = usage.total_tokens

    # DeepSeek 定价（以官网为准，这里用常见价格）
    # 输入: 2元/百万token = 0.002元/千token
    # 输出: 8元/百万token = 0.008元/千token
    prompt_cost = prompt_tokens * 0.002 / 1000
    completion_cost = completion_tokens * 0.008 / 1000
    total_cost = prompt_cost + completion_cost

    # 打印用量信息
    print(f"📊 本轮用量: 输入 {prompt_tokens} | 输出 {completion_tokens} | 合计 {total_tokens} token")
    print(f"💰 本轮花费: ¥{total_cost:.6f} (累计约 ¥{total_cost:.4f})")

    return response.choices[0].message.content

def run_agent():
    print("🤖 代码审查助手已启动，输入 'exit' 退出\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    total_session_tokens = 0
    total_session_cost = 0.0

    while True:
        user_input = input("你: ").strip()

        if user_input.lower() == "exit" or user_input.lower() == "quit":
            print(f"\n📋 会话总结:")
            print(f"   总 token: {total_session_tokens}")
            print(f"   总花费: ¥{total_session_cost:.6f}")
            print("👋 再见！")
            break

        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # 调用前记录，调用后累加
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )

        reply = response.choices[0].message.content
        messages.append({"role": "assistant", "content": reply})

        # 取 usage
        usage = response.usage
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        total_tokens = usage.total_tokens

        # 算钱
        prompt_cost = prompt_tokens * 0.002 / 1000
        completion_cost = completion_tokens * 0.008 / 1000
        turn_cost = prompt_cost + completion_cost

        # 累计
        total_session_tokens += total_tokens
        total_session_cost += turn_cost

        print(f"\n🤖 助手: {reply}")
        print(f"📊 本轮: 输入 {prompt_tokens} | 输出 {completion_tokens} | 合计 {total_tokens} token")
        print(f"💰 本轮: ¥{turn_cost:.6f} | 会话累计: {total_session_tokens} token, ¥{total_session_cost:.6f}")
        print()

if __name__ == "__main__":
    run_agent()