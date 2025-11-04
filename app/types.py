from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ChatStreamBody(BaseModel):
    """
    POST /chat/stream 请求体模型。

    字段说明：
        model: 模型名称（默认使用服务内配置值，可传入兼容）
        input: 用户输入文本（必填）
        sessionId: 会话ID（选填，用于内存上下文）
        system: 覆盖系统提示词（选填）
        systemPromptName: 系统提示词模板名（选填）
        temperature: 采样温度（选填，默认 0.7）
        messages: 自定义历史（选填，优先于 sessionId）
    """

    model: Optional[str] = Field(default="gpt-4o-mini")
    input: str
    sessionId: Optional[str] = None
    system: Optional[str] = None
    systemPromptName: Optional[str] = None
    temperature: Optional[float] = 0.7
    messages: Optional[List[Dict[str, Any]]] = None