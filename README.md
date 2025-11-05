# Chat SSE 服务（Python + FastAPI）

在 `8084` 端口提供 SSE 流式对话服务，调用 OpenAI Responses API（模型已在代码中配置），支持多轮上下文、系统 Prompt 模板管理、错误重试、结构化日志、生命周期追踪与（尽力）Token 用量统计。

## 快速开始

1. 准备环境变量：
   - 将 `.env.example` 复制为 `.env` 并填入 `OPENAI_API_KEY`
2. 安装依赖并启动：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --host 0.0.0.0 --port 8084
   ```

3. 测试接口：
   - 健康检查：`curl http://localhost:8084/healthz`
   - SSE（POST 与 OpenAI 风格一致）：
     ```bash
     curl -N -X POST "http://localhost:8084/chat/stream" \
       -H "Accept: text/event-stream" -H "Content-Type: application/json" \
       -d '{"model":"gpt-4o-mini","input":"你好","sessionId":"abc123","systemPromptName":"default","temperature":0.7}'
     ```
   - SSE（GET 便于浏览器 EventSource）：
     ```bash
     curl -N "http://localhost:8084/chat/stream?input=你好&sessionId=abc123&systemPromptName=default"
     ```

> 若希望在无 API Key 环境下本地验证流式效果，可设置 `USE_MOCK=1`，服务将返回内置模拟事件流。

### 语音克隆集成（可选）

- 环境变量：
  - `VOICE_CLONE_BASE_URL`: 语音克隆服务地址，如 `http://127.0.0.1:8014`
  - `VOICE_CLONE_API_KEY`: 若服务需要鉴权，填入密钥（可选）
  - `VOICE_USE_MOCK`: 设为 `1` 时不调用真实服务，返回模拟音频片段

- SSE 音频事件：当请求头包含 `X-Voice-Id`（或 Query `voiceId`）时，文本事件结束后将继续输出：
  - `audio.chunk`: `data` 为 `{ "b64": "..." }`，表示一段 base64 编码的音频字节
  - `audio.completed`: 表示音频合成完成，包含 `{ voiceId, sessionId }`

- 示例（POST 触发语音）：
  ```bash
  curl -N -X POST "http://localhost:8084/chat/stream" \
    -H "Accept: text/event-stream" -H "Content-Type: application/json" \
    -H "X-Voice-Id: demo-voice" \
    -d '{"input":"这是语音测试","sessionId":"session-env2"}'
  ```

- 对接的 TTS 接口：`POST {VOICE_CLONE_BASE_URL}/api/tts/stream`，请求体字段：
  ```json
  { "text": "...", "session_id": "...", "voice_type": "可选", "save_path": null }
  ```
  服务返回字节流，后端将其分块读取并转为 base64，以上述音频事件推送到同一 SSE 连接。

> 若仅测试语音服务本身，可参考你提供的命令：
> `curl -sS -D headers_env2.txt -X POST http://127.0.0.1:8014/api/tts/stream -H "Content-Type: application/json" -d '{"text": "...", "session_id": "session-env2"}' --output output/long_stream_env2.mp3`

## 目录结构

```
app/
  main.py                # FastAPI 入口与路由
  types.py               # Pydantic 模型
  utils/
    logger.py            # 结构化日志
    retry.py             # 重试策略封装
  services/
    openai_client.py     # OpenAI 流式封装（含模拟）
    session_store.py     # 内存会话管理（TTL+窗口）
    prompts.py           # System Prompt 模板
tests/
  test_chat.py           # 基础测试
```

## 幂等与安全的操作命令（供参考）

```bash
set -euo pipefail
cd /srv/chat

# 权限检查
[ -w . ] || { echo "当前目录不可写"; exit 1; }

# Python 虚拟环境（幂等）
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

# 依赖安装（幂等）
pip install -r requirements.txt

# 启动服务
OPENAI_API_KEY=${OPENAI_API_KEY:-} PORT=${PORT:-8084} uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```

## 测试

```bash
pytest -q
```