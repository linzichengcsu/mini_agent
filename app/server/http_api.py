"""HTTP JSON API：把智能体暴露为可通过 HTTP 调用的服务（标准库实现，零依赖）。

端点一览（全部返回 JSON，编码 UTF-8）：

    GET  /health                      健康检查
    GET  /v1/tools                    列出服务端可用工具声明（JSON Schema）
    POST /v1/chat                     对话（body: {"message": ..., "session_id"?: ...}）
    POST /v1/tools/<name>/execute     直接执行工具（body 即参数字典）
    POST /v1/sessions/<id>/reset      重置指定会话
    GET  /                            服务说明

启动方式：python serve.py --mode http [--host 127.0.0.1] [--port 8000]
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from app.server.service import AgentService

# 请求体大小上限（字节），防止恶意大请求占满内存
MAX_BODY_BYTES = 512 * 1024

# /v1/tools/<name>/execute 的路径匹配
TOOL_EXECUTE_RE = re.compile(r"^/v1/tools/([^/]+)/execute$")
SESSION_RESET_RE = re.compile(r"^/v1/sessions/([^/]+)/reset$")

INDEX_HTML = """mini_agent API 服务已启动。
可用端点：
  GET  /health
  GET  /v1/tools
  POST /v1/chat
  POST /v1/tools/&lt;name&gt;/execute
  POST /v1/sessions/&lt;id&gt;/reset
详见项目 README.md「把智能体变成可被 Java 调用的服务」一节。
"""


class MiniAgentHandler(BaseHTTPRequestHandler):
    """HTTP 处理器：service 通过 server.service 注入。"""

    server_version = "MiniAgentHTTP/1.0"

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @property
    def service(self) -> AgentService:
        return self.server.service  # type: ignore[attr-defined]

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        """读取并解析 JSON 请求体；失败时已发送错误响应并返回 None。"""
        length = self.headers.get("Content-Length")
        try:
            size = int(length) if length else 0
        except ValueError:
            self._send_error_json(400, "Content-Length 不是合法整数")
            return None
        if size > MAX_BODY_BYTES:
            self._send_error_json(413, f"请求体超过上限 {MAX_BODY_BYTES} 字节")
            return None
        try:
            raw = self.rfile.read(size) if size else b"{}"
        except OSError:
            self._send_error_json(400, "读取请求体失败")
            return None
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._send_error_json(400, f"请求体不是合法 JSON（{e}）")
            return None
        if not isinstance(data, dict):
            self._send_error_json(400, "请求体必须是 JSON 对象")
            return None
        return data

    # ------------------------------------------------------------------
    # HTTP 方法
    # ------------------------------------------------------------------
    def do_OPTIONS(self) -> None:  # CORS 预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path in ("/", "/index.html"):
                body = INDEX_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/health":
                self._send_json(self.service.health())
            elif path == "/v1/tools":
                self._send_json({"tools": self.service.list_tools()})
            else:
                self._send_error_json(404, f"未找到端点：{path}")
        except Exception as e:  # noqa: BLE001 —— 兜底，避免连接悬挂
            self._send_error_json(500, f"服务内部错误（{type(e).__name__}: {e}）")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path == "/v1/chat":
                self._handle_chat()
            elif TOOL_EXECUTE_RE.match(path):
                self._handle_execute_tool(TOOL_EXECUTE_RE.match(path).group(1))
            elif SESSION_RESET_RE.match(path):
                self._handle_reset_session(SESSION_RESET_RE.match(path).group(1))
            else:
                self._send_error_json(404, f"未找到端点：{path}")
        except Exception as e:  # noqa: BLE001 —— 兜底，避免连接悬挂
            self._send_error_json(500, f"服务内部错误（{type(e).__name__}: {e}）")

    # ------------------------------------------------------------------
    # 各端点处理
    # ------------------------------------------------------------------
    def _handle_chat(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        message = body.get("message")
        session_id = body.get("session_id")
        max_rounds = body.get("max_rounds")
        if not isinstance(message, str) or not message.strip():
            self._send_error_json(400, "参数 message（字符串）不能为空")
            return
        if session_id is not None and not isinstance(session_id, str):
            self._send_error_json(400, "参数 session_id 必须是字符串")
            return
        if max_rounds is not None and (not isinstance(max_rounds, int) or max_rounds < 1):
            self._send_error_json(400, "参数 max_rounds 必须是正整数")
            return
        self._send_json(self.service.chat(message, session_id, max_rounds))

    def _handle_execute_tool(self, name: str) -> None:
        body = self._read_json_body()
        if body is None:
            return
        result = self.service.execute_tool(name, body)
        status = 200 if result["ok"] else 404
        self._send_json(result, status=status)

    def _handle_reset_session(self, session_id: str) -> None:
        self._send_json(self.service.reset_session(session_id))


class MiniAgentServer(ThreadingHTTPServer):
    """线程化 HTTP 服务器：daemon 线程 + 注入共享 AgentService。"""

    daemon_threads = True

    def __init__(self, addr: Tuple[str, int], service: AgentService) -> None:
        super().__init__(addr, MiniAgentHandler)
        self.service = service


def run_http_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    service: Optional[AgentService] = None,
) -> None:
    """启动 HTTP 服务（阻塞）。Ctrl+C 退出。"""
    service = service or AgentService()
    server = MiniAgentServer((host, port), service)
    url = f"http://{host}:{server.server_address[1]}"
    print(f"🤖 mini_agent HTTP API 服务已启动：{url}")
    print(f"   健康检查: {url}/health    对话: POST {url}/v1/chat")
    print("   按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
        service.close()
