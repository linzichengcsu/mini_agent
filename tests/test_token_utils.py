"""Token 估算相关测试。"""
from app.services.token_utils import count_messages_tokens, estimate_tokens
from tests.base import BaseTestCase


class TestEstimateTokens(BaseTestCase):
    """estimate_tokens 的单元测试。"""

    def test_chinese_char_is_one_token(self):
        self.assertEqual(estimate_tokens("你好世界"), 4)

    def test_cjk_punctuation_counts_as_chinese(self):
        # 全角逗号、句号、感叹号按 1 token 处理（与 tokenizer 行为一致）
        self.assertEqual(estimate_tokens("你好，世界！"), 6)

    def test_ascii_roughly_four_chars_per_token(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)

    def test_empty_string_is_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_mixed_chinese_and_ascii(self):
        # 4 个汉字(4) + 4 个 ASCII(1) = 5
        self.assertEqual(estimate_tokens("你好世界abcd"), 5)

    def test_whitespace_only(self):
        self.assertGreaterEqual(estimate_tokens("   "), 1)


class TestCountMessagesTokens(BaseTestCase):
    """count_messages_tokens 的单元测试。"""

    def test_includes_role_overhead(self):
        messages = [{"role": "user", "content": "你好"}]
        # 4(角色开销) + 2(内容)
        self.assertEqual(count_messages_tokens(messages), 6)

    def test_multiple_messages(self):
        messages = [
            {"role": "user", "content": "你好"},      # 2
            {"role": "assistant", "content": "hello"},  # 5 字符 → 2
        ]
        # 2*4(开销) + 2 + 2
        self.assertEqual(count_messages_tokens(messages), 12)

    def test_empty_messages(self):
        self.assertEqual(count_messages_tokens([]), 0)

    def test_message_missing_content_key(self):
        # 缺少 content 键的消息不应抛异常
        messages = [{"role": "user"}]
        self.assertEqual(count_messages_tokens(messages), 4)
