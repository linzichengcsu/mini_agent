"""Agent 入口相关测试：成本计算 / chat_once / 主循环 / 工具调用循环。"""
import io
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.main import (
    assistant_message_to_dict,
    calculate_cost,
    chat_once,
    run_agent,
)
from app.tools import registry
from tests.base import BaseTestCase


class TestCalculateCost(BaseTestCase):
    """calculate_cost 的单元测试。"""

    def test_zero_tokens_free(self):
        self.assertEqual(calculate_cost(0, 0), 0.0)

    def test_known_pricing(self):
        # 输入 1000 token × 0.002 元/千 + 输出 1000 token × 0.008 元/千 = 0.01 元
        self.assertAlmostEqual(calculate_cost(1000, 1000), 0.01, places=6)

    def test_uses_config_prices(self):
        p_in = settings.PROMPT_PRICE_PER_1K
        p_out = settings.COMPLETION_PRICE_PER_1K
        # 各消耗 1 千 token
        self.assertAlmostEqual(calculate_cost(1000, 1000), (p_in + p_out), places=6)


class TestChatOnce(BaseTestCase):
    """chat_once 的单元测试。"""

    def test_returns_message_and_usage(self):
        message, usage = chat_once([{"role": "user", "content": "hi"}])
        # chat_once 不做 strip（只有摘要才 strip）
        self.assertEqual(message.content, self.DEFAULT_REPLY)
        self.assertEqual(usage.prompt_tokens, 100)
        self.assertEqual(usage.completion_tokens, 50)

    def test_sends_expected_params(self):
        chat_once([{"role": "user", "content": "hi"}])
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], settings.MODEL)
        self.assertEqual(call_kwargs["temperature"], settings.TEMPERATURE)
        self.assertEqual(call_kwargs["max_tokens"], settings.MAX_TOKENS)

    def test_no_tools_param_when_tools_none(self):
        chat_once([{"role": "user", "content": "hi"}])
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("tools", call_kwargs)

    def test_passes_tools_through(self):
        chat_once([{"role": "user", "content": "hi"}], tools=registry.schemas())
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["tools"], registry.schemas())
        self.assertEqual(call_kwargs["tool_choice"], "auto")

    def test_passes_messages_through(self):
        messages = [{"role": "user", "content": "你好"}]
        chat_once(messages)
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["messages"], messages)


class TestAssistantMessageToDict(unittest.TestCase):
    """assistant_message_to_dict 的转换逻辑测试（不依赖网络）。"""

    def test_pydantic_message(self):
        from openai.types.chat.chat_completion_message import ChatCompletionMessage

        message = ChatCompletionMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                }
            ],
        )
        d = assistant_message_to_dict(message)
        self.assertEqual(d["role"], "assistant")
        # content=None 会被 exclude_none 剔除，用 .get 断言为 None
        self.assertIsNone(d.get("content"))
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "read_file")

    def test_mock_message_fallback(self):
        tc = make_tool_call("call_1", "run_shell", '{"command": "ls"}')
        message = MagicMock()
        message.content = None
        message.tool_calls = [tc]
        d = assistant_message_to_dict(message)
        self.assertEqual(d["tool_calls"][0]["id"], "call_1")
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "run_shell")

    def test_plain_content(self):
        message = MagicMock()
        message.content = "最终回复"
        message.tool_calls = None
        d = assistant_message_to_dict(message)
        self.assertEqual(d["content"], "最终回复")
        self.assertEqual(d["tool_calls"], [])


class TestRunAgent(BaseTestCase):
    """主循环的集成测试（mock input 与 client，覆盖核心分支）。"""

    @patch("builtins.input", side_effect=["exit"])
    def test_exit_directly(self, _):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            run_agent()
        text = out.getvalue()
        self.assertIn("再见", text)
        self.fake_client.chat.completions.create.assert_not_called()

    @patch("builtins.input", side_effect=["", "exit"])
    def test_empty_input_skipped(self, _):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            run_agent()
        self.fake_client.chat.completions.create.assert_not_called()

    @patch("builtins.input", side_effect=["请审查这段代码", "exit"])
    def test_normal_conversation(self, _):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            run_agent()
        text = out.getvalue()
        self.assertEqual(self.fake_client.chat.completions.create.call_count, 1)
        self.assertIn("mock 回复", text)
        self.assertIn("会话累计", text)
        self.assertIn("本轮", text)

    @patch("builtins.input", side_effect=["a", "b", "c", "exit"])
    def test_multiple_turns(self, _):
        with patch("sys.stdout", new_callable=io.StringIO):
            run_agent()
        self.assertEqual(self.fake_client.chat.completions.create.call_count, 3)

    def test_messages_sent_to_model_include_system(self):
        # 验证发送给模型的消息以系统提示开头
        with patch("builtins.input", side_effect=["你好", "exit"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                run_agent()
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        sent = call_kwargs["messages"]
        self.assertEqual(sent[0]["role"], "system")
        self.assertEqual(sent[0]["content"], settings.SYSTEM_PROMPT)

    def test_messages_include_tool_schemas(self):
        # 主循环发出的每次请求都应携带工具声明
        with patch("builtins.input", side_effect=["你好", "exit"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                run_agent()
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        names = [t["function"]["name"] for t in call_kwargs["tools"]]
        self.assertEqual(set(names), {"read_file", "run_shell", "search_code", "ask_user"})


def make_tool_call(tool_id: str, name: str, arguments: str):
    """构造一个行为接近 SDK 的 tool_call mock：function.name / arguments 是字符串。"""
    tc = MagicMock(id=tool_id)
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def make_tool_calls_response(tool_calls, usage=None):
    """构造一个带 tool_calls 的假响应（独立于 BaseTestCase，便于直接调用）。"""
    choice = MagicMock()
    choice.message.content = None
    choice.message.tool_calls = tool_calls
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage if usage is not None else MagicMock(
        prompt_tokens=10, completion_tokens=5, total_tokens=15
    )
    return response


class TestRunAgentWithTools(BaseTestCase):
    """主循环的工具调用分支集成测试。"""

    def test_single_tool_call_then_reply(self):
        # 第 1 次调用：模型请求 read_file；第 2 次调用：模型给出最终回复
        tool_call = make_tool_call("call_1", "read_file", '{"path": "main.py"}')
        self.fake_client.chat.completions.create.side_effect = [
            make_tool_calls_response([tool_call]),
            self.fake_response,
        ]

        with patch("builtins.input", side_effect=["请看一下 main.py 的开头", "exit"]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                run_agent()

        text = out.getvalue()
        self.assertIn("调用工具", text)          # 展示工具调用
        self.assertIn("from app.main import", text)  # read_file 真实读取的内容
        self.assertIn("mock 回复", text)         # 展示最终回复
        self.assertEqual(self.fake_client.chat.completions.create.call_count, 2)

        # 第二次请求的消息应包含 assistant(tool_calls) 与 tool 结果
        second = self.fake_client.chat.completions.create.call_args_list[1].kwargs
        roles = [m["role"] for m in second["messages"]]
        self.assertIn("assistant", roles)
        self.assertIn("tool", roles)
        tool_msgs = [m for m in second["messages"] if m["role"] == "tool"]
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_1")

    def test_unknown_tool_error_passed_to_model(self):
        # 模型请求了未注册的工具：错误信息应作为 tool 结果回传，不崩溃
        tool_call = make_tool_call("call_x", "no_such_tool", "{}")
        self.fake_client.chat.completions.create.side_effect = [
            make_tool_calls_response([tool_call]),
            self.fake_response,
        ]

        with patch("builtins.input", side_effect=["用不存在的工具做点事", "exit"]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                run_agent()

        text = out.getvalue()
        self.assertIn("未知工具", text)
        self.assertIn("mock 回复", text)

    def test_tool_loop_stops_at_round_limit(self):
        # 模型每次都请求工具调用 → 触发 MAX_TOOL_ROUNDS 兜底，不再无限循环
        tool_call = make_tool_call("call_loop", "search_code", '{"pattern": "x"}')
        calls = [make_tool_calls_response([tool_call])] * settings.MAX_TOOL_ROUNDS
        self.fake_client.chat.completions.create.side_effect = calls

        with patch("builtins.input", side_effect=["一直搜下去", "exit"]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                run_agent()

        text = out.getvalue()
        self.assertIn("达到上限", text)
        self.assertEqual(
            self.fake_client.chat.completions.create.call_count,
            settings.MAX_TOOL_ROUNDS,
        )
