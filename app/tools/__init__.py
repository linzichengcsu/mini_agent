"""工具层：注册表 + 内置工具。

默认注册表 registry 已注册 read_file / run_shell / search_code / ask_user 四个基础工具。

【如何添加新工具】（详见 README.md）：
  1. 在 builtin.py 中新建一个继承 Tool 的类（或新建模块）；
  2. 在下方用 registry.register(YourTool()) 注册。
之后 Agent 即可通过 tool_calls 使用它，主循环无需改动。
"""
from app.tools.base import Tool, ToolRegistry
from app.tools.builtin import (
    AskUserTool,
    ReadFileTool,
    RunShellTool,
    SearchCodeTool,
)

# 全局注册表：app.main 与测试均通过它执行工具
registry = ToolRegistry()
registry.register(ReadFileTool())
registry.register(RunShellTool())
registry.register(SearchCodeTool())
registry.register(AskUserTool())

__all__ = ["Tool", "ToolRegistry", "registry"]
