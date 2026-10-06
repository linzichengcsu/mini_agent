"""工具调用基础设施：Tool 基类与 ToolRegistry 注册表。

设计目标：新增一个工具只需要两步——
  1. 继承 Tool，实现 run()（定义 name / description / parameters）；
  2. 在 app/tools/__init__.py 中 register()。
主循环与模型的交互逻辑无需任何改动，即插即用。
详细教程见项目根目录 README.md「如何添加新工具」。
"""
import json
import os
from typing import Any, Dict, List, Optional


class Tool:
    """单个工具的定义。子类必须覆写 name / description / parameters / run。"""

    name: str = ""
    description: str = ""
    # JSON Schema（type=object），描述工具接受的参数，供模型生成调用参数
    parameters: Dict[str, Any] = {}

    def to_openai_schema(self) -> Dict[str, Any]:
        """把工具声明转为 OpenAI tools 参数格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs) -> str:
        """执行工具，返回给模型的纯文本结果（成功或错误信息）。"""
        raise NotImplementedError(f"工具 {self.name} 未实现 run()")


class ToolRegistry:
    """工具注册表：按名字登记工具，并按 OpenAI tool_calls 协议执行。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """登记一个工具；同名工具会覆盖旧实现（便于替换）。"""
        if not tool.name:
            raise ValueError("工具必须有非空 name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def schemas(self) -> List[Dict[str, Any]]:
        """返回全部工具的 OpenAI 声明列表，直接作为 chat.completions 的 tools 参数。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: str) -> str:
        """执行一个工具调用。

        arguments 为模型返回的 JSON 字符串。任何错误（未知工具、参数不合法、
        工具内部异常）都转换为文本错误信息返回给模型，让模型有机会修正后重试，
        而不是把异常抛到主循环导致对话中断。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"错误：未知工具「{name}」，可用工具：{', '.join(self._tools)}"

        try:
            kwargs = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            if not isinstance(kwargs, dict):
                return f"错误：工具参数必须是 JSON 对象，收到 {type(kwargs).__name__}"
            return str(tool.run(**kwargs))
        except json.JSONDecodeError as e:
            return f"错误：工具参数不是合法 JSON（{e}）"
        except TypeError as e:
            return f"错误：工具参数与签名不匹配（{e}）"
        except Exception as e:  # 工具内部错误同样交回给模型处理
            return f"错误：工具执行失败（{type(e).__name__}: {e}）"


def is_subpath(path: str, parent: str) -> bool:
    """判断 path 是否位于 parent 目录之内（含 parent 本身）。两者都会被规范化为绝对路径。"""
    try:
        real_path = os.path.realpath(path)
        real_parent = os.path.realpath(parent)
        return os.path.commonpath([real_path, real_parent]) == real_parent
    except ValueError:  # 跨盘符（如 C: 与 D:）时 commonpath 抛 ValueError
        return False


def ensure_within_allowed(path: str) -> str:
    """校验并规范化路径；超出 settings.TOOLS_ALLOWED_DIRS 时抛 PermissionError。

    供 read_file / search_code / run_shell(workdir) 使用，防止模型越权访问
    项目目录之外的文件。允许目录为空列表时不做限制。
    """
    from app.core.config import settings  # 延迟导入，避免循环依赖

    full = os.path.abspath(os.path.expanduser(path))
    allowed = settings.TOOLS_ALLOWED_DIRS
    if allowed and not any(is_subpath(full, d) for d in allowed):
        raise PermissionError(
            f"路径不允许访问：{full}（允许目录：{allowed}）"
        )
    return full
