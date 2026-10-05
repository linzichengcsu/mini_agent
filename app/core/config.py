"""应用配置：模型参数、上下文窗口、定价等全部可调参数集中于此。"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class Settings:
    """集中管理模型调用与上下文压缩相关的全部可调参数。"""

    # ---- 模型 ----
    MODEL = "deepseek-chat"

    # ---- 上下文窗口 ----
    MAX_CONTEXT_TOKENS = 64000        # 模型上下文窗口上限（deepseek-chat 为 64K）
    COMPRESS_THRESHOLD = 0.75         # 上下文使用率达到该比例时触发压缩
    SAFETY_MARGIN = 2000              # 为模型回复预留的 token 余量，防止“上下文+输出”超窗报错
    KEEP_RECENT_TURNS = 6             # 压缩时保留的最近完整对话轮数（每轮 = 1 问 + 1 答）
    SUMMARY_MAX_TOKENS = 800          # 摘要允许的最大 token 数
    MIN_SUMMARIZE_TOKENS = 300        # 早期对话至少多大才值得调用模型做摘要，否则直接丢弃

    # ---- 对话与摘要参数 ----
    TEMPERATURE = 0.7
    MAX_TOKENS = 500
    SUMMARY_TEMPERATURE = 0.3

    # ---- 定价（元/千 token，以 DeepSeek 官网为准）----
    PROMPT_PRICE_PER_1K = 0.002       # 输入
    COMPLETION_PRICE_PER_1K = 0.008   # 输出

    # ---- 系统提示词——定义 Agent 的人设和行为 ----
    SYSTEM_PROMPT = """你是一个代码审查助手。
你的职责是帮助开发者发现代码中的潜在问题，并给出改进建议。
用简洁的中文回答，一次只聚焦一个问题。"""


settings = Settings()


def get_client() -> OpenAI:
    """创建 DeepSeek 的 OpenAI 兼容客户端（从 .env 读取 API Key）。"""
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
