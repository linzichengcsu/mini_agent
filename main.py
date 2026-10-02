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
    """调一次 LLM，返回回复内容"""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.7,
        max_tokens=500
    )
    return response.choices[0].message.content

def run_agent():
    """Agent 主循环"""
    print("🤖 代码审查助手已启动，输入 'exit' 退出\n")

    # 消息历史——这是 Agent 的"记忆"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    while True:
        user_input = input("你: ").strip()

        if user_input.lower() == "exit":
            print("👋 再见！")
            break

        if not user_input:
            continue

        # 把用户输入加入历史
        messages.append({"role": "user", "content": user_input})

        # 调 LLM
        reply = chat_once(messages)

        # 把助手回复加入历史（关键！没有这行就没有记忆）
        messages.append({"role": "assistant", "content": reply})

        print(f"\n🤖 助手: {reply}\n")

if __name__ == "__main__":
    run_agent()