"""应用配置：模型参数、上下文窗口、定价等全部可调参数集中于此。"""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 项目根目录（本文件位于 <root>/app/core/config.py，上上级即根目录）
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


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

    # ---- 工具调用 ----
    MAX_TOOL_ROUNDS = 10           # 单次用户请求内，模型最多连续发起几轮工具调用（防止死循环）
    SHELL_TIMEOUT = 30             # run_shell 命令执行超时（秒），超时即终止
    SHELL_MAX_OUTPUT = 8000        # run_shell 最多返回给模型的输出字符数
    SEARCH_MAX_RESULTS = 50        # search_code 最多返回的匹配行数
    READ_FILE_MAX_CHARS = 50000    # read_file 单次最多返回的字符数
    # read_file / search_code / run_shell(workdir) 允许访问的目录；
    # 置为空列表 [] 表示不限制（不推荐，尤其是与 run_shell 配合时）
    TOOLS_ALLOWED_DIRS = [PROJECT_ROOT]

    # ---- 定价（元/千 token，以 DeepSeek 官网为准）----
    PROMPT_PRICE_PER_1K = 0.002       # 输入
    COMPLETION_PRICE_PER_1K = 0.008   # 输出

    # ---- 系统提示词——定义 Agent 的人设和行为 ----
    SYSTEM_PROMPT = """你是一个代码审查助手，也是一个可以使用工具行动的智能体。
你的职责是帮助开发者发现代码中的潜在问题，并给出改进建议。
你可以使用以下工具来辅助工作：
- read_file：读取文件内容；
- run_shell：执行 shell 命令（如运行测试、查看目录结构）；
- search_code：在项目中搜索代码；
- ask_user：需求不明确时向用户提问。

使用规则：
1. 需要看代码时优先使用 read_file / search_code，不要凭空猜测代码内容；
2. 需要验证运行结果（如测试、语法检查）时使用 run_shell；
3. 信息不足、需求含糊或需要用户决策时，用 ask_user 向用户确认，不要臆测；
4. 用简洁的中文回答，一次只聚焦一个问题。"""


settings = Settings()


def get_client() -> OpenAI:
    """创建 DeepSeek 的 OpenAI 兼容客户端（从 .env 读取 API Key）。"""
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
