import os
import json
from typing import Any, Dict, Iterable, List, Optional

from app.utils.retry import retry_with_backoff


class MockEvent:
    """
    模拟的流式事件对象，兼容 event.type 与 event.data 访问。
    """

    def __init__(self, event_type: str, data: Dict[str, Any]):
        self.type = event_type
        self.data = data


class MockStream:
    """
    模拟的事件流，便于在无 API Key 环境下本地验证 SSE。
    """

    def __init__(self, reply_text: str):
        self.reply_text = reply_text

    def __iter__(self):
        return self.events()

    def events(self) -> Iterable[MockEvent]:
        yield MockEvent("response.created", {"id": "mock-001"})
        yield MockEvent("message.start", {})
        # 逐字/逐段输出
        for ch in self.reply_text:
            yield MockEvent("content.delta", {"delta": ch})
        yield MockEvent("message.stop", {})
        usage = {"input_tokens": 0, "output_tokens": len(self.reply_text), "total_tokens": len(self.reply_text)}
        yield MockEvent("response.usage", usage)
        yield MockEvent("response.completed", {})

    def get_final_response(self) -> Dict[str, Any]:
        return {"usage": {"input_tokens": 0, "output_tokens": len(self.reply_text), "total_tokens": len(self.reply_text)}}


class OpenAIClient:
    """
    OpenAI 客户端封装，负责发起 Responses API 流式请求。

    方法：
        stream_response(input_messages, temperature): 返回可迭代事件流对象

    关键逻辑：
        - 当环境变量 USE_MOCK=1 时，返回模拟事件流。
        - 正常情况下调用 OpenAI 官方 SDK 的 responses.stream 接口，启用 include_usage。
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.use_mock = os.environ.get("USE_MOCK", "0") == "1"

    @retry_with_backoff()
    def _stream_impl(self, input_messages: List[Dict[str, Any]], temperature: float):
        if self.use_mock or not self.api_key:
            return MockStream("这是一个模拟流式回复，用于本地验证SSE。")
        # 使用 Chat Completions 流式作为兼容实现
        from openai import OpenAI

        def convert_to_chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            chat_msgs: List[Dict[str, Any]] = []
            for m in messages:
                role = m.get("role")
                content = m.get("content")
                text = ""
                if isinstance(content, list):
                    # Responses 风格 [{type:text, text:...}] -> 提取 text
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text += c.get("text", "")
                elif isinstance(content, str):
                    text = content
                chat_msgs.append({"role": role, "content": text})
            return chat_msgs

        client = OpenAI(api_key=self.api_key)
        chat_messages = convert_to_chat_messages(input_messages)
        # 返回一个适配器，将 Chat Completions 的流事件转为统一的 MockEvent 风格
        return ChatCompletionsStreamAdapter(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=chat_messages,
                temperature=temperature,
                stream=True,
            )
        )

    def stream_response(self, input_messages: List[Dict[str, Any]], temperature: float = 0.7):
        """
        发起流式请求。

        输入：
            input_messages: Responses API 的 input 消息数组（包含系统、历史与当前用户消息）
            temperature: 采样温度，默认 0.7

        输出：
            事件流对象，可被迭代获取事件。
        """
        return self._stream_impl(input_messages, temperature)


class ChatCompletionsStreamAdapter:
    """
    将 OpenAI Chat Completions 的流式响应适配为统一事件。

    事件序：
        response.created -> message.start -> 多个 content.delta -> message.stop -> response.completed

    使用统计：
        Chat Completions 流式通常不直接提供 usage，这里提供近似统计（输出字符数）。
    """

    def __init__(self, generator):
        self._gen = generator
        self._buffer = []  # 收集最终文本

    def __iter__(self):
        return self.events()

    def events(self) -> Iterable[MockEvent]:
        yield MockEvent("response.created", {"id": "chatcmpl-stream"})
        yield MockEvent("message.start", {})
        for chunk in self._gen:
            try:
                choice = chunk.choices[0]
                delta_text = getattr(choice.delta, "content", None)
                if delta_text:
                    self._buffer.append(delta_text)
                    yield MockEvent("content.delta", {"delta": delta_text})
            except Exception:
                # 保护性忽略异常块
                continue
        yield MockEvent("message.stop", {})
        text = "".join(self._buffer)
        usage = {"input_tokens": 0, "output_tokens": len(text), "total_tokens": len(text)}
        yield MockEvent("response.usage", usage)
        yield MockEvent("response.completed", {})

    def get_final_response(self) -> Dict[str, Any]:
        text = "".join(self._buffer)
        return {"usage": {"input_tokens": 0, "output_tokens": len(text), "total_tokens": len(text)}}