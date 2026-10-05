"""公共测试基类：提供 mock 的 OpenAI 客户端。

所有测试全程不产生真实 API 请求：
  - app.main 与 app.services.context 的模块级 client 会被替换为假客户端；
  - 假客户端返回可编程的响应（内容、usage），并记录调用参数供断言。
"""
import unittest
from unittest.mock import MagicMock, patch

import app.main as main_module
import app.services.context as context_module


class BaseTestCase(unittest.TestCase):
    """所有测试类的基类。"""

    # 假客户端的默认响应内容（注意保留首尾空格，用于验证 strip 行为）
    DEFAULT_REPLY = "  mock 回复  "

    def setUp(self):
        # ---- 构造假响应 ----
        self.fake_choice = MagicMock()
        self.fake_choice.message.content = self.DEFAULT_REPLY

        self.fake_usage = MagicMock()
        self.fake_usage.prompt_tokens = 100
        self.fake_usage.completion_tokens = 50
        self.fake_usage.total_tokens = 150

        self.fake_response = MagicMock()
        self.fake_response.choices = [self.fake_choice]
        self.fake_response.usage = self.fake_usage

        # ---- 构造假客户端 ----
        self.fake_client = MagicMock()
        self.fake_client.chat.completions.create.return_value = self.fake_response

        # ---- 替换两个模块级 client ----
        self._patchers = [
            patch.object(context_module, "client", self.fake_client),
            patch.object(main_module, "client", self.fake_client),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.addCleanup(self._stop_patchers)

    def _stop_patchers(self):
        for patcher in self._patchers:
            patcher.stop()
