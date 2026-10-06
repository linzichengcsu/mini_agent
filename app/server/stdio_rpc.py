"""stdio JSON-RPC：通过 stdin/stdout 逐行交换 JSON 的子进程协议。

适用于 Java 用 ProcessBuilder 直接启动 Python 进程、以"本地调用"方式
使用智能体（无需端口、无需防火墙放行），协议规则：

- 请求：stdin 每行一个 JSON 对象：{"id": <任意数字>, "method": <方法名>, "params": {...}}
- 响应：stdout 每行一个 JSON 对象：{"id": <与请求一致>, "result": {...}}
- 出错时返回：{"id": <与请求一致>, "error": {"code": <数字>, "message": <字符串>}}
- 服务端永远不向 stdout 输出协议之外的内容；日志/异常走 stderr。

方法：
    health          -> {status, service, model, sessions, tools}
    list_tools      -> {tools: [schema...]}
    execute_tool    -> params {name, arguments} -> {tool, arguments, ok, result}
    chat            -> params {message, session_id?, max_rounds?} -> 同 HTTP /v1/chat
    reset_session   -> params {session_id} -> {ok, session_id}

启动方式：python serve.py --mode stdio
"""
import json
import sys
from typing import Any, Dict, Optional

from app.server.service import AgentService

# JSON-RPC 错误码
ERR_PARSE = -32700       # 无法解析的 JSON
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603


def _ok(req_id: Any, result: Dict[str, Any]) -> str:
    return json.dumps({"id": req_id, "result": result}, ensure_ascii=False)


def _err(req_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"id": req_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


def handle_request(req: Dict[str, Any], service: AgentService) -> str:
    """处理一个 JSON-RPC 请求对象，返回要写入 stdout 的一行 JSON 字符串。"""
    req_id = req.get("id")
    method = req.get("method")
    if not isinstance(method, str) or not method:
        return _err(req_id, ERR_INVALID_REQUEST, "缺少 method 字段")
    params = req.get("params") or {}
    if not isinstance(params, dict):
        return _err(req_id, ERR_INVALID_PARAMS, "params 必须是 JSON 对象")

    try:
        if method == "health":
            return _ok(req_id, service.health())
        if method == "list_tools":
            return _ok(req_id, {"tools": service.list_tools()})
        if method == "execute_tool":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                return _err(req_id, ERR_INVALID_PARAMS, "params.name 不能为空")
            if not isinstance(arguments, dict):
                return _err(req_id, ERR_INVALID_PARAMS, "params.arguments 必须是 JSON 对象")
            return _ok(req_id, service.execute_tool(name, arguments))
        if method == "chat":
            message = params.get("message")
            if not isinstance(message, str) or not message.strip():
                return _err(req_id, ERR_INVALID_PARAMS, "params.message 不能为空")
            session_id = params.get("session_id")
            if session_id is not None and not isinstance(session_id, str):
                return _err(req_id, ERR_INVALID_PARAMS, "params.session_id 必须是字符串")
            max_rounds = params.get("max_rounds")
            if max_rounds is not None and (not isinstance(max_rounds, int) or max_rounds < 1):
                return _err(req_id, ERR_INVALID_PARAMS, "params.max_rounds 必须是正整数")
            return _ok(req_id, service.chat(message, session_id, max_rounds))
        if method == "reset_session":
            session_id = params.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                return _err(req_id, ERR_INVALID_PARAMS, "params.session_id 不能为空")
            return _ok(req_id, service.reset_session(session_id))
        return _err(req_id, ERR_METHOD_NOT_FOUND, f"未知方法：{method}")
    except Exception as e:  # noqa: BLE001 —— 任何内部错误都作为 JSON-RPC 错误返回
        return _err(req_id, ERR_INTERNAL, f"{type(e).__name__}: {e}")


def handle_line(line: str, service: AgentService) -> str:
    """处理一行输入，返回一行输出。供测试与循环共用。"""
    line = line.strip()
    if not line:
        return ""
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        return _err(None, ERR_PARSE, f"无法解析的 JSON（{e}）")
    if not isinstance(req, dict):
        return _err(None, ERR_INVALID_REQUEST, "请求必须是 JSON 对象")
    return handle_request(req, service)


def _force_utf8_stdio() -> None:
    """确保 stdin/stdout 使用 UTF-8，避免 Windows 管道下中文乱码。"""
    for stream in (sys.stdin, sys.stdout):
        try:
            if getattr(stream, "encoding", None) and stream.encoding.lower() != "utf-8":
                stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass  # 非 TextIOWrapper 或已关闭时忽略


def serve_stdio(service: Optional[AgentService] = None) -> None:
    """进入 stdio 事件循环（阻塞，直到 stdin 关闭）。"""
    _force_utf8_stdio()
    service = service or AgentService()
    for line in sys.stdin:
        out = handle_line(line, service)
        if out:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
    service.close()
