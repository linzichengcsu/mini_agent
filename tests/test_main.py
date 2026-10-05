"""Agent 入口相关测试：成本计算 / chat_once / 主循环。"""
import io
from unittest.mock import patch

from app.core.config import settings
from app.main import calculate_cost, chat_once, run_agent
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

    def test_returns_reply_and_usage(self):
        reply, usage = chat_once([{"role": "user", "content": "hi"}])
        # chat_once 不做 strip（只有摘要才 strip）
        self.assertEqual(reply, self.DEFAULT_REPLY)
        self.assertEqual(usage.prompt_tokens, 100)
        self.assertEqual(usage.completion_tokens, 50)

    def test_sends_expected_params(self):
        chat_once([{"role": "user", "content": "hi"}])
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], settings.MODEL)
        self.assertEqual(call_kwargs["temperature"], settings.TEMPERATURE)
        self.assertEqual(call_kwargs["max_tokens"], settings.MAX_TOKENS)

    def test_passes_messages_through(self):
        messages = [{"role": "user", "content": "你好"}]
        chat_once(messages)
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["messages"], messages)


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
