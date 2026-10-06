"""AgentService：供外部程序（如 Java）调用智能体的统一服务内核。

职责：
- 管理多个并发会话（内存存储，线程安全），支持多轮对话；
- 执行"模型 ⇄ 工具"循环（复用 app.main.run_turn）；
- 允许直接执行工具（绕过模型，适合程序化调用 read_file / run_shell 等）；
- 服务端模式下从工具列表中移除 ask_user（它依赖交互式终端 input()）。

本类不依赖任何传输层（HTTP / stdio），可被任意调用方或测试直接驱动。
"""
import threading
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.main import run_turn
from app.services.context import maybe_compress
from app.tools import registry

# 服务端模式不暴露给模型的工具：ask_user 依赖交互终端 input()，
# API/子进程场景没有"坐在终端前的用户"，保留只会让模型陷入死路。
SERVER_DISABLED_TOOLS = {"ask_user"}


def _new_session_messages() -> List[Dict[str, str]]:
    return [{"role": "system", "content": settings.SYSTEM_PROMPT}]


class AgentService:
    """智能体服务内核：会话管理 + 对话 + 直接执行工具。

    Args:
        max_sessions: 内存中最多保存的会话数；超出时淘汰最久未使用的会话。
        max_rounds: 单次对话内模型最多连续发起的工具轮次；None 用配置默认值。
    """

    def __init__(self, max_sessions: int = 100, max_rounds: Optional[int] = None) -> None:
        self.max_sessions = max_sessions
        self.max_rounds = max_rounds

        # 会话存储：{session_id: [messages]}；OrderedDict 便于按使用顺序淘汰最旧
        self._sessions: "OrderedDict[str, List[dict]]" = OrderedDict()
        # 每个会话一把锁，保证同一会话内的多轮请求串行执行
        self._locks: Dict[str, threading.Lock] = {}
        # 保护 _sessions / _locks 的全局锁（临界区极小）
        self._guard = threading.Lock()

        # 服务端可用的工具声明（移除 ask_user）
        self._tools: List[Dict[str, Any]] = [
            s for s in registry.schemas()
            if s["function"]["name"] not in SERVER_DISABLED_TOOLS
        ]

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    def _get_or_create_session(self, session_id: Optional[str]) -> str:
        """返回可用会话 id；不存在时新建（内部加锁、处理上限淘汰）。"""
        with self._guard:
            if session_id and session_id in self._sessions:
                sid = session_id
                self._sessions.move_to_end(sid)
                return sid

            sid = session_id or uuid.uuid4().hex
            if len(self._sessions) >= self.max_sessions:
                oldest = next(iter(self._sessions))
                self._sessions.pop(oldest)
                self._locks.pop(oldest, None)
            self._sessions[sid] = _new_session_messages()
            self._locks[sid] = threading.Lock()
            return sid

    def _session_lock(self, session_id: str) -> Optional[threading.Lock]:
        with self._guard:
            return self._locks.get(session_id)

    def new_session_id(self) -> str:
        """显式创建一个空会话，返回其 id。"""
        return self._get_or_create_session(None)

    def reset_session(self, session_id: str) -> dict:
        """清空指定会话的历史，回到只含系统提示的初始状态。"""
        lock = self._session_lock(session_id)
        if lock is None:
            return {"ok": False, "error": f"会话不存在：{session_id}"}
        with lock:
            if session_id in self._sessions:
                self._sessions[session_id] = _new_session_messages()
        return {"ok": True, "session_id": session_id}

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """健康检查。"""
        return {
            "status": "ok",
            "service": "mini_agent",
            "model": settings.MODEL,
            "sessions": len(self._sessions),
            "tools": [s["function"]["name"] for s in self._tools],
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        """返回服务端可用工具的完整 OpenAI 声明列表。"""
        return list(self._tools)

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> dict:
        """直接执行一个工具（不经过模型）。

        arguments 是参数字典（如 {"path": "main.py"}）。返回：
        {"tool", "arguments", "ok": bool, "result": str}
        """
        if name in SERVER_DISABLED_TOOLS:
            return {
                "tool": name,
                "arguments": arguments,
                "ok": False,
                "result": (
                    f"错误：工具「{name}」依赖交互式终端提问，"
                    "在 API / 子进程服务模式下不可用。"
                ),
            }
        tool = registry.get(name)
        if tool is None:
            return {
                "tool": name,
                "arguments": arguments,
                "ok": False,
                "result": f"错误：未知工具「{name}」，可用工具：{registry.names()}",
            }
        result = registry.execute(name, dict(arguments or {}))
        return {"tool": name, "arguments": dict(arguments or {}), "ok": True, "result": result}

    def chat(self, message: str, session_id: Optional[str] = None, max_rounds: Optional[int] = None) -> dict:
        """提交一条用户消息，返回智能体回复与统计（含本回合工具调用记录）。

        不传 session_id 则创建新会话；传 session_id 则在原会话基础上继续多轮对话。
        """
        if not message or not str(message).strip():
            return {
                "session_id": session_id or "",
                "reply": "",
                "error": "消息不能为空",
            }

        sid = self._get_or_create_session(session_id)
        lock = self._session_lock(sid)
        with lock:
            messages = self._sessions[sid]
            messages.append({"role": "user", "content": str(message)})

            # 上下文窗口限制 + 摘要压缩（超过阈值时自动压缩早期对话）
            messages, _ = maybe_compress(messages)

            stats = run_turn(
                messages,
                tools=self._tools,
                max_rounds=max_rounds if max_rounds is not None else self.max_rounds,
                collect_tool_calls=True,
            )

        return {
            "session_id": sid,
            "reply": stats["reply"],
            "prompt_tokens": stats["prompt_tokens"],
            "completion_tokens": stats["completion_tokens"],
            "total_tokens": stats["total_tokens"],
            "cost": stats["cost"],
            "tool_calls": stats["tool_calls"],
        }

    def close(self) -> None:
        """释放资源（清空会话）。"""
        with self._guard:
            self._sessions.clear()
            self._locks.clear()
