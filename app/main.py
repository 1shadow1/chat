import os
import json
import uuid
from typing import Any, Dict, Iterable, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from app.types import ChatStreamBody
from app.utils.logger import setup_logger, log_json, get_content_log_config, build_preview, write_session_log
from app.services.openai_client import OpenAIClient
from app.services.session_store import SessionStore
from app.services.prompts import PROMPTS
from dotenv import load_dotenv
from app.services.voice_client import VoiceClient


load_dotenv()  # 加载 .env 环境变量，确保 OPENAI_API_KEY、PORT 等可用
logger = setup_logger()
app = FastAPI(title="Chat SSE Service")
_content_cfg = get_content_log_config()

# CORS 配置
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

session_store = SessionStore()
client = OpenAIClient()
voice_client = VoiceClient()


def build_messages(system_text: Optional[str], history: List[dict], user_input: str) -> List[dict]:
    """
    构建 Responses API 的 input 消息数组。

    输入：
        system_text: 系统提示词文本（可为空）
        history: 历史消息列表（role+content）
        user_input: 当前用户输入文本

    输出：
        List[dict]: 消息数组，包含 system（若有）、历史与当前 user 消息。

    关键逻辑：
        - 每条消息的 content 使用富文本格式：[{"type":"text","text":...}]
    """
    messages: List[dict] = []
    if system_text:
        messages.append({
            "role": "system",
            "content": [{"type": "text", "text": system_text}],
        })
    # 历史消息直接拼接（已按相同格式保存）
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": user_input}],
    })
    return messages


def to_sse(event: str, data: Dict[str, Any]) -> str:
    """
    将事件与数据编码为 SSE 文本块。

    输入：
        event: 事件名称
        data: 数据载荷（字典）

    输出：
        str: SSE 块（包含 event 与 data 行，结尾空行）
    """
    return f"event: {event}\n" + f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_generator(stream, request_id: str, session_id: Optional[str]) -> Iterable[bytes]:
    """
    将 OpenAI 流式事件转为 SSE 输出的生成器。

    输入：
        stream: OpenAI responses.stream 返回的可迭代事件对象或模拟流
        request_id: 本次请求唯一ID
        session_id: 会话ID（可空）

    输出：
        可迭代的字节序列，供 StreamingResponse 使用。

    关键逻辑：
        - 事件映射：统一输出 response.created、message.start、content.delta、message.stop、response.usage、response.completed、response.error。
        - 末尾尝试读取最终 usage 并输出。
    """
    # 首事件：meta
    log_json(logger, 20, "sse.response.created", requestId=request_id, sessionId=session_id)
    write_session_log(session_id, "INFO", "sse.response.created", {"requestId": request_id})
    yield to_sse("response.created", {"requestId": request_id, "sessionId": session_id}).encode("utf-8")
    try:
        for event in stream:
            etype = getattr(event, "type", None) or getattr(event, "event_type", None) or ""
            data = getattr(event, "data", None)
            # 文本增量
            if "delta" in etype or etype in ("content.delta", "response.output_text.delta"):
                delta = None
                if data and isinstance(data, dict):
                    delta = data.get("delta") or data.get("text")
                else:
                    delta = getattr(event, "delta", None)
                if delta:
                    log_json(logger, 10, "sse.content.delta", requestId=request_id, len=len(delta))
                    # 可选：记录增量预览
                    if _content_cfg.get("include_output") in ("delta", "both"):
                        pv = build_preview(delta, _content_cfg["max_chars"], _content_cfg["redact"])
                        log_json(logger, 10, "sse.content.delta.preview", requestId=request_id, **pv)
                        write_session_log(session_id, "DEBUG", "sse.content.delta.preview", {"requestId": request_id, **pv})
                    yield to_sse("content.delta", {"text": delta}).encode("utf-8")
                    continue
            # 直接透传已知事件
            if etype in ("message.start", "message.stop"):
                log_json(logger, 10, "sse.message", requestId=request_id, type=etype)
                yield to_sse(etype, data if isinstance(data, dict) else {}).encode("utf-8")
                continue
            if etype in ("response.usage",):
                try:
                    usage = data if isinstance(data, dict) else {}
                except Exception:
                    usage = {}
                log_json(logger, 20, "sse.response.usage", requestId=request_id, **usage)
                yield to_sse("response.usage", data if isinstance(data, dict) else {}).encode("utf-8")
                continue
            if etype in ("response.completed",):
                log_json(logger, 20, "sse.response.completed", requestId=request_id)
                yield to_sse("response.completed", data if isinstance(data, dict) else {}).encode("utf-8")
                continue
            # 未知事件：忽略或记录
            # 可选：yield to_sse("debug.event", {"type": etype, "data": data or {}}).encode("utf-8")
        # 最终响应（包含 usage）
        try:
            final = stream.get_final_response()
            usage = final.get("usage") if isinstance(final, dict) else getattr(final, "usage", None)
            # 聚合 final 文本（若可用）
            final_text = None
            # OpenAI Responses 最终对象可能含有 output_text 或 content；容错提取
            if isinstance(final, dict):
                final_text = final.get("output_text") or final.get("text")
            else:
                final_text = getattr(final, "output_text", None) or getattr(final, "text", None)
            if usage:
                log_json(logger, 20, "sse.response.usage.final", requestId=request_id, **(usage if isinstance(usage, dict) else {}))
                write_session_log(session_id, "INFO", "sse.response.usage.final", {"requestId": request_id, **(usage if isinstance(usage, dict) else {})})
                yield to_sse("response.usage", usage if isinstance(usage, dict) else {}).encode("utf-8")
            # 可选：记录最终输出预览
            if _content_cfg.get("include_output") in ("final", "both") and final_text:
                pv = build_preview(final_text, _content_cfg["max_chars"], _content_cfg["redact"])
                log_json(logger, 20, "sse.output.final.preview", requestId=request_id, **pv)
                write_session_log(session_id, "INFO", "sse.output.final.preview", {"requestId": request_id, **pv})
        except Exception:
            pass
        log_json(logger, 20, "sse.response.completed.final", requestId=request_id)
        write_session_log(session_id, "INFO", "sse.response.completed.final", {"requestId": request_id})
        yield to_sse("response.completed", {}).encode("utf-8")
    except Exception as e:
        # 错误时记录输出状态（可选）
        log_json(logger, 40, "sse.response.error", requestId=request_id, error=str(e))
        write_session_log(session_id, "ERROR", "sse.response.error", {"requestId": request_id, "error": str(e)})
        yield to_sse("response.error", {"message": str(e)}).encode("utf-8")


def stream_with_voice(stream, text_for_tts: str, voice_id: Optional[str], request_id: str, session_id: Optional[str]) -> Iterable[bytes]:
    """
    同步合成语音并在同一 SSE 流中输出音频片段事件。

    输入：
        stream: 文本生成事件流（OpenAI）
        text_for_tts: 用于 TTS 的文本（可为最终合成文本或用户输入）
        voice_id: 音色ID（可空，空则不输出音频）
        request_id: 请求ID
        session_id: 会话ID

    输出：
        SSE 字节序列，包含文本事件与音频事件：
            - 文本：content.delta、response.completed 等
            - 音频：audio.chunk（data: { b64: "..." }）

    关键逻辑：
        - 先发送文本事件（与原逻辑一致）。
        - 若提供 voice_id，则调用 VoiceClient.synthesize_stream(text, session_id, voice_id) 按字节流生成音频，逐块发送。
    """
    # 先透传文本事件
    for chunk in stream_generator(stream, request_id, session_id):
        yield chunk
    # 生成音频
    if voice_id:
        # 会话ID用于 TTS 服务端维护流状态；若无，则使用请求ID占位
        sid_for_tts = session_id or request_id
        log_json(logger, 20, "tts.request.start", requestId=request_id, sessionId=sid_for_tts, voiceId=voice_id)
        for audio_evt in voice_client.synthesize_stream(text_for_tts, sid_for_tts, voice_id):
            size = len(audio_evt.get("b64", "")) if isinstance(audio_evt, dict) else 0
            log_json(logger, 10, "tts.chunk", requestId=request_id, size=size)
            yield to_sse("audio.chunk", audio_evt).encode("utf-8")
        log_json(logger, 20, "tts.request.completed", requestId=request_id, sessionId=sid_for_tts, voiceId=voice_id)
        yield to_sse("audio.completed", {"voiceId": voice_id, "sessionId": sid_for_tts}).encode("utf-8")


@app.get("/healthz")
def healthz():
    """
    健康检查接口。

    输出：
        JSON：{"status": "ok"}
    """
    return {"status": "ok"}


@app.get("/prompts")
def list_prompts():
    """
    列出可用的 System Prompt 模板名与摘要。
    """
    return {"prompts": [{"name": k, "preview": PROMPTS[k][:40]} for k in PROMPTS.keys()]}


@app.get("/prompts/{name}")
def get_prompt(name: str):
    """
    获取指定模板文本。
    """
    text = PROMPTS.get(name)
    if not text:
        return JSONResponse(status_code=404, content={"error": "prompt not found"})
    return {"name": name, "text": text}


@app.post("/chat/stream")
async def chat_stream_post(body: ChatStreamBody, request: Request):
    """
    SSE 主入口（POST），与 OpenAI Responses API 风格一致。

    输入：
        body: ChatStreamBody，请求体
        request: FastAPI 请求对象（用于访问头等）

    输出：
        StreamingResponse：`text/event-stream`，按事件流式返回。

    关键逻辑：
        - 支持 systemPromptName 与 system 覆盖；
        - 支持 sessionId 多轮上下文；
        - lifecycle：生成 requestId 并记录日志；
        - 输出事件对齐：response.created、delta、usage、completed、error。
    """
    request_id = str(uuid.uuid4())
    session_id = body.sessionId
    system_text = body.system or PROMPTS.get(body.systemPromptName or "default")

    # 历史：优先使用 body.messages，否则从 sessionStore 获取
    if body.messages:
        session_store.set(session_id or request_id, body.messages)
        history = body.messages
    else:
        history = session_store.get(session_id or request_id)

    messages = build_messages(system_text, history, body.input)

    log_json(logger, 20, "request.start", requestId=request_id, sessionId=session_id, path="/chat/stream")
    write_session_log(session_id, "INFO", "request.start", {"requestId": request_id, "path": "/chat/stream"})
    # 可选：记录输入预览
    if _content_cfg.get("include_input"):
        # 提取当前用户输入（忽略历史）
        pv = build_preview(body.input, _content_cfg["max_chars"], _content_cfg["redact"])
        log_json(logger, 20, "request.input.preview", requestId=request_id, messages=len(messages), **pv)
        write_session_log(session_id, "INFO", "request.input.preview", {"requestId": request_id, "messages": len(messages), **pv})
    stream = client.stream_response(messages, body.temperature or 0.7)

    async def run_stream() -> Iterable[bytes]:
        # 生成器本身是同步的，这里直接迭代即可
        # 合成语音的文本：优先使用用户输入，可根据需要改为最终文本（需收集缓冲）
        tts_text = body.input
        voice_id = request.headers.get("X-Voice-Id") or request.query_params.get("voiceId")
        for chunk in stream_with_voice(stream, tts_text, voice_id, request_id, session_id):
            yield chunk
        # 记录结束日志
        log_json(logger, 20, "request.end", requestId=request_id, sessionId=session_id)
        write_session_log(session_id, "INFO", "request.end", {"requestId": request_id})
        # 写入会话历史：将最后一轮助手回复粗略追加（此处近似，真实可在收集完整文本后追加）
        # 简化：不在生成器中收集全文，后续可优化。
        # 这里只追加一个占位，避免误删历史。
        session_store.append(session_id or request_id, {"role": "assistant", "content": [{"type": "text", "text": "(流式回复已发送)"}]})

    return StreamingResponse(run_stream(), media_type="text/event-stream")


@app.get("/chat/stream")
async def chat_stream_get(input: str, sessionId: Optional[str] = None, system: Optional[str] = None, systemPromptName: Optional[str] = None, temperature: Optional[float] = 0.7):
    """
    SSE 兼容入口（GET），便于浏览器 EventSource 使用。

    输入：
        input: 用户输入文本（Query）
        sessionId: 会话ID（Query）
        system: 覆盖系统提示词
        systemPromptName: 模板名
        temperature: 采样温度

    输出：
        StreamingResponse：`text/event-stream`。
    """
    body = ChatStreamBody(input=input, sessionId=sessionId, system=system, systemPromptName=systemPromptName, temperature=temperature)
    # 复用 POST 处理逻辑，同时传递 Query 参数 voiceId（若存在）
    req = Request(scope={"type": "http"})
    # FastAPI TestClient/Request 在此场景下 query_params 为空，这里不强制注入；
    # 前端若需 GET 使用 voiceId，建议改为 POST 传递或使用 Header。
    return await chat_stream_post(body, req)