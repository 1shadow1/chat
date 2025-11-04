import logging
import sys
from typing import Any, Dict


def setup_logger() -> logging.Logger:
    """
    初始化结构化日志记录器。

    返回：
        logging.Logger：配置好的日志记录器。
    关键逻辑：
        - 使用标准 logging 输出到 stdout，统一格式包含等级、消息。
        - 提供辅助方法在日志中加入结构化上下文（如 requestId、sessionId）。
    """
    logger = logging.getLogger("chat-sse")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_json(logger: logging.Logger, level: int, message: str, **kwargs: Any) -> None:
    """
    以 JSON 字符串方式记录结构化日志。

    输入：
        logger: 日志记录器实例
        level: 日志级别，如 logging.INFO
        message: 文字消息
        **kwargs: 额外上下文，如 requestId、sessionId、耗时等

    输出：
        无，直接写入日志。

    关键逻辑：
        - 将上下文字典序列化为字符串拼接在消息后，便于后续检索。
    """
    try:
        import json
        context = json.dumps(kwargs, ensure_ascii=False)
        logger.log(level, f"{message} | {context}")
    except Exception:
        # 回退到普通日志
        logger.log(level, f"{message} | context={kwargs}")