import logging
import os
import sys
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler
import re
from datetime import datetime


def setup_logger() -> logging.Logger:
    """
    初始化结构化日志记录器，支持控制台与文件持久化。

    输入：
        无（从环境变量读取配置）

    输出：
        logging.Logger：配置好的日志记录器。

    关键逻辑：
        - 标准输出：始终输出到 stdout，统一格式包含等级、消息；
        - 文件持久化（可选）：当 `LOG_TO_FILE=1` 时，使用按大小滚动的文件记录；
          配置项：
            - LOG_FILE_PATH：日志文件路径，默认 `/srv/chat/logs/chat.log`；
            - LOG_MAX_BYTES：单文件最大字节数，默认 10_485_760（10MB）；
            - LOG_BACKUP_COUNT：保留滚动文件个数，默认 5；
        - 提供 `log_json` 辅助方法记录结构化上下文（如 requestId、sessionId）。
    """
    logger = logging.getLogger("chat-sse")
    if not logger.handlers:
        # 读取日志等级（默认 INFO）
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level_value = getattr(logging, level_name, logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

        # 控制台输出
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level_value)
        console.setFormatter(formatter)
        logger.addHandler(console)

        # 文件持久化（按大小滚动）
        if os.environ.get("LOG_TO_FILE", "0") == "1":
            # 选择默认日志路径：优先适配现有 /srv/chat/log/ 目录，其次使用 /srv/chat/logs/
            default_path = "/srv/chat/logs/chat.log"
            try:
                if os.path.isdir("/srv/chat/log"):
                    default_path = "/srv/chat/log/chat.log"
                elif os.path.isdir("/srv/chat/logs"):
                    default_path = "/srv/chat/logs/chat.log"
            except Exception:
                pass
            log_path = os.environ.get("LOG_FILE_PATH", default_path)
            max_bytes = int(os.environ.get("LOG_MAX_BYTES", "10485760"))  # 10MB 默认
            backup_count = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
            # 确保目录存在
            log_dir = os.path.dirname(log_path)
            try:
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
            except Exception:
                # 若目录创建失败，不影响服务启动，仅继续控制台日志
                pass
            try:
                file_handler = RotatingFileHandler(
                    log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
                )
                file_handler.setLevel(level_value)
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            except Exception:
                # 文件句柄创建失败时，退回仅控制台输出
                pass

        # 设置根记录器等级
        logger.setLevel(level_value)
        try:
            import json as _json
            # 读取内容日志相关配置以便初始化时可见
            cfg = get_content_log_config()
            logger.info(
                f"logger.init | "
                + _json.dumps({
                    "level": level_name,
                    "to_file": os.environ.get("LOG_TO_FILE", "0") == "1",
                    "path": os.environ.get("LOG_FILE_PATH", default_path if 'default_path' in locals() else None),
                    "content": cfg,
                }, ensure_ascii=False)
            )
        except Exception:
            pass
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


def get_content_log_config() -> Dict[str, Any]:
    """
    读取内容日志相关配置。

    输出：
        Dict：
          - include_input: bool 是否记录用户输入预览
          - include_output: str 输出记录模式（none|delta|final|both）
          - max_chars: int 单条内容最大记录字符数
          - redact: bool 是否启用基础脱敏

    关键逻辑：
        - 从进程环境变量读取；提供合理默认值；校验 include_output 合法性。
    """
    include_input = os.environ.get("LOG_INCLUDE_INPUT", "0") == "1"
    include_output = os.environ.get("LOG_INCLUDE_OUTPUT", "none").lower()
    if include_output not in ("none", "delta", "final", "both"):
        include_output = "none"
    try:
        max_chars = int(os.environ.get("LOG_CONTENT_MAX_CHARS", "1000"))
    except Exception:
        max_chars = 1000
    redact = os.environ.get("LOG_REDACT_ENABLED", "0") == "1"
    return {
        "include_input": include_input,
        "include_output": include_output,
        "max_chars": max_chars,
        "redact": redact,
    }


def _redact_text(text: str) -> str:
    """
    基础脱敏处理：邮箱、手机号、疑似密钥等模式。

    输入：
        text: 原始文本

    输出：
        str: 脱敏后的文本

    关键逻辑：
        - 邮箱：保留用户名首字符与域名首字符，其余以 * 替代；
        - 手机号/长数字串：替换为部分星号；
        - 可能的密钥：apiKey/token/secret/password 键名后的值进行遮蔽。
    """
    try:
        # 邮箱遮蔽
        email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        def _mask_email(m: re.Match) -> str:
            v = m.group(0)
            at = v.find("@")
            if at == -1:
                return "***@***"
            name = v[:at]
            domain = v[at+1:]
            masked_name = (name[0] + "***") if name else "***"
            masked_domain = (domain.split(".")[0][:1] + "***") if domain else "***"
            return f"{masked_name}@{masked_domain}"
        text = email_pattern.sub(_mask_email, text)

        # 手机号/长数字串遮蔽（宽松）
        phone_pattern = re.compile(r"\b(\+?\d[\d\- ]{7,}\d)\b")
        text = phone_pattern.sub(lambda m: m.group(0)[:3] + "***" + m.group(0)[-2:], text)

        # 键名后的值遮蔽
        secret_pattern = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*([A-Za-z0-9\-_/]{8,})")
        text = secret_pattern.sub(lambda m: m.group(1) + "=***", text)
        return text
    except Exception:
        return text


def build_preview(text: Optional[str], max_chars: int, redact: bool) -> Dict[str, Any]:
    """
    构造内容预览，包含长度与截断后片段。

    输入：
        text: 原始文本（可为 None）
        max_chars: 最大记录字符数（超过将截断）
        redact: 是否开启基础脱敏

    输出：
        Dict：{"text_len": int, "preview": str}

    关键逻辑：
        - 按需进行脱敏；
        - 超长内容截断并加标识；
        - 为空时返回长度 0 与空预览。
    """
    if not text:
        return {"text_len": 0, "preview": ""}
    try:
        src = text
        if redact:
            src = _redact_text(src)
        if len(src) > max_chars:
            return {"text_len": len(text), "preview": src[:max_chars] + "…(截断)"}
        else:
            return {"text_len": len(text), "preview": src}
    except Exception:
        return {"text_len": len(text), "preview": text[:max_chars] + ("…(截断)" if len(text) > max_chars else "")}


def write_session_log(session_id: Optional[str], level: str, message: str, payload: Dict[str, Any]) -> None:
    """
    将指定事件写入会话级独立日志文件。

    输入：
        session_id: 会话ID（为空则不写入）
        level: 文本级别（如 "INFO"、"DEBUG"、"ERROR"）
        message: 事件名称（如 request.input.preview）
        payload: 结构化上下文字典（将以 JSON 写入）

    输出：
        无，写入到 `/srv/chat/log/<sessionId>/<sessionId>.log`（可配置）。

    关键逻辑：
        - 受环境变量 `SESSION_LOG_ENABLED` 控制，默认关闭；
        - 路径可通过 `SESSION_LOG_BASE_DIR` 配置，默认 `/srv/chat/log`；
        - 自动创建目录；采用简单追加写入，不做滚动。
    """
    try:
        if not session_id:
            return
        if os.environ.get("SESSION_LOG_ENABLED", "0") != "1":
            return
        base_dir = os.environ.get("SESSION_LOG_BASE_DIR", "/srv/chat/log")
        # 目录：<base>/<sessionId>/，文件：<sessionId>.log
        target_dir = os.path.join(base_dir, session_id)
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, f"{session_id}.log")
        # 时间戳与消息格式对齐主日志
        ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        import json
        line = f"{ts} {level} {message} | " + json.dumps(payload, ensure_ascii=False)
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # 静默失败，避免影响主流程
        pass