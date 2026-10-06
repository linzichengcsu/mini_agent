"""API 服务层测试：AgentService 内核 / HTTP JSON API / stdio JSON-RPC。

全程使用 mock 客户端（BaseTestCase 注入的假客户端），不发真实模型请求；
直接执行工具只跑 read_file、echo 等无害操作。
"""
import json
import queue
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.core.config import settings
from app.server.http_api import MiniAgentHandler, MiniAgentServer
from app.server.service import AgentService
from app.server.stdio_rpc import handle_line
from tests.base import BaseTestCase
from tests.test_main import make_tool_call, make_tool_calls_response


class TestAgentService(BaseTestCase):
    """AgentService 内核：对话、工具循环、会话管理、直接执行工具。"""

    def setUp(self):
        super().setUp()
        self.service = AgentService()

    def tearDown(self):
        self.service.close()
        super().tearDown()

    # ---- 对话 ----
    def test_chat_returns_reply_and_session(self):
        result = self.service.chat("你好")
        self.assertEqual(result["reply"], self.DEFAULT_REPLY)
        self.assertTrue(result["session_id"])
        self.assertEqual(result["prompt_tokens"], 100)
        self.assertEqual(result["completion_tokens"], 50)

    def test_chat_empty_message_returns_error(self):
        result = self.service.chat("   ")
        self.assertIn("error", result)
        self.assertEqual(result["reply"], "")
        self.fake_client.chat.completions.create.assert_not_called()

    def test_chat_with_tool_call_loop(self):
        # 第 1 次调用模型请求 read_file，第 2 次给出最终回复
        tool_call = make_tool_call("call_1", "read_file", '{"path": "main.py"}')
        self.fake_client.chat.completions.create.side_effect = [
            make_tool_calls_response([tool_call]),
            self.fake_response,
        ]
        result = self.service.chat("请看一下 main.py")
        self.assertEqual(result["reply"], self.DEFAULT_REPLY)
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(result["tool_calls"][0]["name"], "read_file")
        self.assertIn("项目入口", result["tool_calls"][0]["result"])
        self.assertEqual(self.fake_client.chat.completions.create.call_count, 2)

    def test_chat_stops_at_round_limit(self):
        tool_call = make_tool_call("call_x", "search_code", '{"pattern": "zzz_never_match_123"}')
        calls = [make_tool_calls_response([tool_call])] * settings.MAX_TOOL_ROUNDS
        self.fake_client.chat.completions.create.side_effect = calls
        result = self.service.chat("一直搜下去")
        self.assertIn("达到上限", result["reply"])
        self.assertEqual(
            self.fake_client.chat.completions.create.call_count,
            settings.MAX_TOOL_ROUNDS,
        )

    # ---- 会话管理 ----
    def test_same_session_keeps_history(self):
        self.service.chat("你好", session_id="s1")
        self.service.chat("再见", session_id="s1")
        calls = self.fake_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        # system + user1 + assistant1 + user2 + assistant2 = 5 条
        self.assertEqual(len(calls[1].kwargs["messages"]), 5)
        self.assertEqual(calls[1].kwargs["messages"][-1]["content"], self.DEFAULT_REPLY)

    def test_different_sessions_are_isolated(self):
        self.service.chat("你好", session_id="a")
        self.service.chat("再见", session_id="b")
        calls = self.fake_client.chat.completions.create.call_args_list
        # 会话 b 只有 system + user + assistant = 3 条
        self.assertEqual(len(calls[1].kwargs["messages"]), 3)

    def test_unknown_session_id_creates_new_session(self):
        result = self.service.chat("你好", session_id="brand_new")
        self.assertEqual(result["session_id"], "brand_new")

    def test_reset_session(self):
        self.service.chat("你好", session_id="s1")
        r = self.service.reset_session("s1")
        self.assertTrue(r["ok"])
        r2 = self.service.reset_session("not_exists")
        self.assertFalse(r2["ok"])

    def test_session_eviction_when_over_limit(self):
        service = AgentService(max_sessions=2)
        service.chat("一", session_id="s1")
        service.chat("二", session_id="s2")
        service.chat("三", session_id="s3")
        # s1 应被淘汰（最旧）
        self.assertFalse(service.reset_session("s1")["ok"])
        self.assertTrue(service.reset_session("s2")["ok"])
        self.assertTrue(service.reset_session("s3")["ok"])
        service.close()

    # ---- 直接执行工具 ----
    def test_execute_tool_ok(self):
        r = self.service.execute_tool("read_file", {"path": "main.py"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["tool"], "read_file")
        self.assertIn("项目入口", r["result"])

    def test_execute_tool_unknown(self):
        r = self.service.execute_tool("no_such_tool", {})
        self.assertFalse(r["ok"])
        self.assertIn("未知工具", r["result"])

    def test_execute_tool_ask_user_disabled(self):
        r = self.service.execute_tool("ask_user", {"question": "x"})
        self.assertFalse(r["ok"])
        self.assertIn("不可用", r["result"])

    def test_execute_shell_echo(self):
        r = self.service.execute_tool("run_shell", {"command": "echo hello-mini-agent"})
        self.assertTrue(r["ok"])
        self.assertIn("hello-mini-agent", r["result"])

    def test_execute_shell_forbidden_command(self):
        r = self.service.execute_tool("run_shell", {"command": "rm -rf /tmp/x"})
        self.assertTrue(r["ok"])  # 安全拦截属于"正常返回"，不是执行失败
        self.assertIn("安全策略禁止", r["result"])

    # ---- 工具列表 / 健康检查 ----
    def test_list_tools_excludes_ask_user(self):
        names = [s["function"]["name"] for s in self.service.list_tools()]
        self.assertEqual(set(names), {"read_file", "run_shell", "search_code"})
        self.assertNotIn("ask_user", names)

    def test_health(self):
        h = self.service.health()
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["model"], settings.MODEL)


class TestHttpApi(BaseTestCase):
    """HTTP JSON API：用真实 ThreadingHTTPServer 做端到端请求。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 关闭访问日志，避免测试输出刷屏
        MiniAgentHandler.log_message = lambda *a, **k: None

    def setUp(self):
        super().setUp()
        self.service = AgentService()
        self.server: ThreadingHTTPServer = MiniAgentServer(("127.0.0.1", 0), self.service)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.service.close)

    def tearDown(self):
        super().tearDown()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path, body=None):
        data = json.dumps(body if body is not None else {}).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health(self):
        status, data = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_tools(self):
        status, data = self._get("/v1/tools")
        self.assertEqual(status, 200)
        names = [t["function"]["name"] for t in data["tools"]]
        self.assertEqual(set(names), {"read_file", "run_shell", "search_code"})

    def test_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/no/such/endpoint")
        self.assertEqual(ctx.exception.code, 404)

    def test_chat_ok(self):
        status, data = self._post("/v1/chat", {"message": "你好"})
        self.assertEqual(status, 200)
        self.assertTrue(data["session_id"])
        self.assertEqual(data["reply"], self.DEFAULT_REPLY)

    def test_chat_with_session(self):
        _, r1 = self._post("/v1/chat", {"message": "第一句", "session_id": "abc"})
        self.assertEqual(r1["session_id"], "abc")
        _, r2 = self._post("/v1/chat", {"message": "第二句", "session_id": "abc"})
        self.assertEqual(r2["session_id"], "abc")
        calls = self.fake_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls[1].kwargs["messages"]), 5)

    def test_chat_empty_message_bad_request(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/chat", {"message": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_chat_invalid_json_bad_request(self):
        req = urllib.request.Request(
            self.base + "/v1/chat", data=b"{not json", method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=15)
        self.assertEqual(ctx.exception.code, 400)

    def test_execute_tool_endpoint(self):
        status, data = self._post("/v1/tools/read_file/execute", {"path": "main.py"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("项目入口", data["result"])

    def test_execute_unknown_tool_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/tools/no_such/execute", {})
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("未知工具", body["result"])

    def test_execute_ask_user_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/v1/tools/ask_user/execute", {"question": "x"})
        self.assertEqual(ctx.exception.code, 404)

    def test_reset_session_endpoint(self):
        self._post("/v1/chat", {"message": "你好", "session_id": "abc"})
        status, data = self._post("/v1/sessions/abc/reset")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])


class TestStdioRpc(BaseTestCase):
    """stdio JSON-RPC：handle_line 单元级测试。"""

    def setUp(self):
        super().setUp()
        self.service = AgentService()

    def tearDown(self):
        self.service.close()
        super().tearDown()

    def _call(self, line):
        return json.loads(handle_line(line, self.service))

    def test_health(self):
        resp = self._call('{"id": 1, "method": "health", "params": {}}')
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["status"], "ok")

    def test_list_tools(self):
        resp = self._call('{"id": 2, "method": "list_tools", "params": {}}')
        names = [t["function"]["name"] for t in resp["result"]["tools"]]
        self.assertNotIn("ask_user", names)

    def test_execute_tool(self):
        resp = self._call(
            '{"id": 3, "method": "execute_tool", "params": '
            '{"name": "read_file", "arguments": {"path": "main.py"}}}'
        )
        self.assertTrue(resp["result"]["ok"])
        self.assertIn("项目入口", resp["result"]["result"])

    def test_chat(self):
        resp = self._call('{"id": 4, "method": "chat", "params": {"message": "你好"}}')
        self.assertEqual(resp["result"]["reply"], self.DEFAULT_REPLY)
        self.assertTrue(resp["result"]["session_id"])

    def test_chat_missing_message_error(self):
        resp = self._call('{"id": 5, "method": "chat", "params": {}}')
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_unknown_method(self):
        resp = self._call('{"id": 6, "method": "nope", "params": {}}')
        self.assertEqual(resp["error"]["code"], -32601)

    def test_invalid_json(self):
        resp = json.loads(handle_line("not json at all", self.service))
        self.assertEqual(resp["error"]["code"], -32700)

    def test_reset_session(self):
        self._call('{"id": 6, "method": "chat", "params": {"message": "你好", "session_id": "s1"}}')
        resp = self._call('{"id": 7, "method": "reset_session", "params": {"session_id": "s1"}}')
        self.assertTrue(resp["result"]["ok"])

    def test_reset_unknown_session_error(self):
        resp = self._call('{"id": 8, "method": "reset_session", "params": {"session_id": "ghost"}}')
        self.assertFalse(resp["result"]["ok"])


@unittest.skipIf(sys.platform == "win32" and sys.version_info < (3, 8), "需要 Python 3.8+ 的管道 reconfigure")
class TestStdioRpcEndToEnd(unittest.TestCase):
    """stdio 真实子进程端到端测试：启动 serve.py --mode stdio 并交互。"""

    @classmethod
    def setUpClass(cls):
        import os

        cls.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _readline(self, proc, timeout=20):
        q = queue.Queue()

        def _read():
            try:
                q.put(proc.stdout.readline())
            except Exception as e:  # noqa: BLE001
                q.put(e)

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            proc.terminate()
            self.fail("stdio 端到端测试超时：服务端未响应")

    def test_end_to_end(self):
        proc = subprocess.Popen(
            [sys.executable, "serve.py", "--mode", "stdio"],
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        try:
            proc.stdin.write('{"id": 1, "method": "health", "params": {}}\n')
            proc.stdin.flush()
            line = self._readline(proc)
            resp = json.loads(line)
            self.assertEqual(resp["id"], 1)
            self.assertEqual(resp["result"]["status"], "ok")

            proc.stdin.write(
                '{"id": 2, "method": "execute_tool", "params": '
                '{"name": "run_shell", "arguments": {"command": "echo stdio-e2e"}}}\n'
            )
            proc.stdin.flush()
            line = self._readline(proc)
            resp = json.loads(line)
            self.assertIn("stdio-e2e", resp["result"]["result"])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
