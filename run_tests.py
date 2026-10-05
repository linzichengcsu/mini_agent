"""一键测试运行器：项目的统一测试入口。

集中注册并运行 tests/ 包下全部测试模块，替代裸的 `unittest discover`。

【如何添加新的测试模块】（只需两步，其他逻辑无需改动）
  1. 在 tests/ 下新建 test_xxx.py，内部用 unittest.TestCase 写测试类；
  2. 在本文件顶部的注册区 import 该模块并加入 TEST_MODULES 列表。
完成。

【运行方式】（PowerShell，在项目根目录）
    .\.venv\Scripts\python.exe run_tests.py            # 运行全部测试
    .\.venv\Scripts\python.exe run_tests.py test_xxx   # 只运行某个模块

退出码：0 = 全部通过；1 = 存在失败/错误（可在脚本中通过 $LASTEXITCODE 判断）。
"""
import os
import sys
import unittest
from typing import Optional

# 保证从任意工作目录运行本脚本，都能正确导入 app / tests 包
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# =====================================================================
# 注册区：以后新增测试模块，import 并加入下方 TEST_MODULES 列表即可
# =====================================================================
from tests import test_context, test_main, test_token_utils

TEST_MODULES = [
    test_token_utils,   # token 估算
    test_context,       # 摘要压缩 / 上下文窗口限制
    test_main,          # 成本计算 / chat_once / 主循环
]
# =====================================================================


def build_suite(only: Optional[str] = None) -> unittest.TestSuite:
    """组装测试套件；only 用于按模块名子串过滤（如 'test_context'）。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in TEST_MODULES:
        if only and only not in module.__name__:
            continue
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    suite = build_suite(only)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
