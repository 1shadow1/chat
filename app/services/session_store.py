import time
from typing import Dict, List, Any


class SessionStore:
    """
    内存会话存储，支持 TTL 与窗口限制。

    说明：
        - 使用字典维护 sessionId -> {messages: List[dict], ts: float}
        - 每条消息结构与 Responses API 的 input 消息格式一致（role+content）。

    参数：
        ttl_seconds: 会话存活时间，默认 7200 秒（2 小时）
        max_rounds: 保留的最近轮数，默认 10

    方法：
        get(session_id): 返回消息历史（过期则清理）
        append(session_id, message): 追加消息
        set(session_id, messages): 设置完整历史
    """

    def __init__(self, ttl_seconds: int = 7200, max_rounds: int = 10):
        self.ttl_seconds = ttl_seconds
        self.max_rounds = max_rounds
        self.store: Dict[str, Dict[str, Any]] = {}

    def _is_expired(self, ts: float) -> bool:
        return (time.time() - ts) > self.ttl_seconds

    def get(self, session_id: str) -> List[dict]:
        data = self.store.get(session_id)
        if not data:
            return []
        if self._is_expired(data["ts"]):
            del self.store[session_id]
            return []
        return data["messages"]

    def append(self, session_id: str, message: dict) -> None:
        messages = self.get(session_id)
        messages.append(message)
        # 窗口限制：仅保留最近 max_rounds*2 条（user+assistant 成对）
        if len(messages) > self.max_rounds * 2:
            messages = messages[-self.max_rounds * 2 :]
        self.store[session_id] = {"messages": messages, "ts": time.time()}

    def set(self, session_id: str, messages: List[dict]) -> None:
        # 直接设置历史（例如从请求体传入 messages 覆盖）
        if len(messages) > self.max_rounds * 2:
            messages = messages[-self.max_rounds * 2 :]
        self.store[session_id] = {"messages": messages, "ts": time.time()}