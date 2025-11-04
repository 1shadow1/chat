import os
import sys


def pytest_sessionstart(session):
    """
    在测试会话开始时，为 Python 解释器追加项目根目录到 sys.path。

    这样测试模块可以使用 `from app.main import app` 进行导入。
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if root not in sys.path:
        sys.path.insert(0, root)