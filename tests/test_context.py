"""摘要压缩与上下文窗口限制相关测试。"""
from unittest.mock import patch

from app.core.config import settings
from app.services.context import maybe_compress, summarize_conversation
from app.services.token_utils import count_messages_tokens
from tests.base import BaseTestCase


def build_long_conversation(turns=30, fill=1000):
    """构造一段足够长、会触发压缩阈值的对话。"""
    messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
    for i in range(turns):
        messages.append({"role": "user", "content": f"用户问题{i}" + "，" * fill})
        messages.append({"role": "assistant", "content": f"助手回答{i}" + "，" * fill})
    return messages


def compress_threshold():
    """计算触发压缩的 token 阈值。"""
    limit = settings.MAX_CONTEXT_TOKENS - settings.SAFETY_MARGIN
    return int(limit * settings.COMPRESS_THRESHOLD)


class TestSummarizeConversation(BaseTestCase):
    """summarize_conversation 的单元测试。"""

    def test_returns_stripped_summary(self):
        # BaseTestCase 的假响应内容带首尾空格，验证调用方会 strip
        summary = summarize_conversation([{"role": "user", "content": "测试"}])
        self.assertEqual(summary, "mock 回复")

    def test_sends_expected_summary_prompt(self):
        summarize_conversation([{"role": "user", "content": "测试"}])
        self.fake_client.chat.completions.create.assert_called_once()
        call_kwargs = self.fake_client.chat.completions.create.call_args.kwargs

        self.assertEqual(call_kwargs["model"], settings.MODEL)
        self.assertEqual(call_kwargs["temperature"], settings.SUMMARY_TEMPERATURE)
        self.assertEqual(call_kwargs["max_tokens"], settings.SUMMARY_MAX_TOKENS)

        messages = call_kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("请压缩以下对话", messages[1]["content"])


class TestMaybeCompress(BaseTestCase):
    """maybe_compress 的单元测试（mock 掉摘要调用，不产生真实请求）。"""

    def test_no_compression_below_threshold(self):
        messages = [
            {"role": "system", "content": settings.SYSTEM_PROMPT},
            {"role": "user", "content": "请审查这段代码"},
            {"role": "assistant", "content": "好的"},
        ]
        out, before = maybe_compress(messages, verbose=False)
        self.assertIs(out, messages)  # 同一对象，未被改动
        self.assertEqual(before, count_messages_tokens(messages))

    def test_compress_when_over_threshold(self):
        messages = build_long_conversation()
        before = count_messages_tokens(messages)
        self.assertGreater(before, compress_threshold())

        with patch(
            "app.services.context.summarize_conversation",
            return_value="（摘要：早期对话）",
        ) as mock_summary:
            out, _ = maybe_compress(messages, verbose=False)

        # 只调用了一次摘要，且确实传入的是“早期”部分
        mock_summary.assert_called_once()
        self.assertEqual(len(mock_summary.call_args.args[0]), len(messages) - 1 - settings.KEEP_RECENT_TURNS * 2)

        # 结构：系统提示 + 摘要 + 最近保留区
        roles = [m["role"] for m in out]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[1], "system")
        self.assertIn("【历史对话摘要】", out[1]["content"])
        self.assertEqual(len(out), 2 + settings.KEEP_RECENT_TURNS * 2)
        self.assertEqual(out[-1]["content"], "助手回答29" + "，" * 1000)
        self.assertLess(count_messages_tokens(out), before)

    def test_early_tail_kept_intact(self):
        # 最近几轮对话必须原样保留（顺序、内容不变）
        messages = build_long_conversation()
        with patch(
            "app.services.context.summarize_conversation",
            return_value="摘要",
        ):
            out, _ = maybe_compress(messages, verbose=False)

        recent = out[2:]
        expected = messages[-settings.KEEP_RECENT_TURNS * 2:]
        self.assertEqual(recent, expected)

    def test_drop_old_when_too_small(self):
        # 早期内容不足 MIN_SUMMARIZE_TOKENS 时直接丢弃，不调用模型。
        # 注意：超长消息控制在“超过压缩阈值但低于硬上限”，避免触发兜底截断分支。
        messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
        for i in range(7):
            messages.append({"role": "user", "content": f"短{i}"})
            messages.append({"role": "assistant", "content": f"短{i}"})
        messages.append({"role": "user", "content": "很长" * 30000})
        before = count_messages_tokens(messages)
        self.assertGreater(before, compress_threshold())
        # 丢弃早期后应低于硬上限，不触发兜底截断
        self.assertLess(before, settings.MAX_CONTEXT_TOKENS - settings.SAFETY_MARGIN)

        with patch("app.services.context.summarize_conversation") as mock_summary:
            out, _ = maybe_compress(messages, verbose=False)

        mock_summary.assert_not_called()
        self.assertEqual(out[0]["role"], "system")
        self.assertNotIn("摘要", out[1]["content"])
        self.assertEqual(out[-1]["content"], "很长" * 30000)

    def test_fallback_truncate_oversized_message(self):
        # 单条消息超过硬上限时兜底截断（摘要与系统提示不受影响）
        messages = [
            {"role": "system", "content": settings.SYSTEM_PROMPT},
            {"role": "user", "content": "粘贴的超大代码 " + "a" * 300000},
        ]
        out, _ = maybe_compress(messages, verbose=False)
        self.assertLessEqual(
            count_messages_tokens(out),
            settings.MAX_CONTEXT_TOKENS - settings.SAFETY_MARGIN,
        )
        self.assertIn("已截断", out[1]["content"])

    def test_system_prompt_never_truncated(self):
        # 兜底截断只作用于非 system 消息
        messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
        messages.append({"role": "user", "content": "很长" * 100000})
        out, _ = maybe_compress(messages, verbose=False)
        self.assertEqual(out[0]["content"], settings.SYSTEM_PROMPT)
