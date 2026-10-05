"""项目入口（兼容 `python main.py` 启动方式）。

完整实现位于 app/ 包内，此处仅做转发，保持原有使用习惯不变。
"""
from app.main import run_agent

if __name__ == "__main__":
    run_agent()
