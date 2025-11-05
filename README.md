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

### 日志配置

- 复制 `.env.example` 为 `.env` 后，按需配置：
  - `LOG_TO_FILE=1` 开启文件持久化（默认仅控制台）；
  - `LOG_FILE_PATH=/srv/chat/log/chat.log` 指定日志文件；
  - `LOG_LEVEL=DEBUG` 查看细粒度增量与音频块日志；

- 默认行为：若 `LOG_FILE_PATH` 未设置，服务会优先写入 `/srv/chat/log/chat.log`（如果目录存在），否则写入 `/srv/chat/logs/chat.log`。

- 示例：直接使用 uvicorn 启动也会加载 `.env` 并写入日志文件。
  ```bash
  # 确保有 .env 并包含 LOG_TO_FILE/LOG_FILE_PATH/LOG_LEVEL
  uvicorn app.main:app --host 0.0.0.0 --port 8084
  # 验证日志：
  tail -n 100 /srv/chat/log/chat.log
  ```

#### 内容日志与脱敏

- 为降低泄露风险，默认不记录原始输入/输出文本；可通过以下变量精确开启：
  - `LOG_INCLUDE_INPUT=0|1` 是否记录用户输入预览；
  - `LOG_INCLUDE_OUTPUT=none|delta|final|both` 输出记录模式；
  - `LOG_CONTENT_MAX_CHARS=1000` 单条预览最大字符数（超出截断）；
  - `LOG_REDACT_ENABLED=1` 开启基础脱敏（邮箱、手机号、疑似密钥）。

- 示例：记录最终输出预览并脱敏（建议在开发环境）：
  ```env
  LOG_LEVEL=DEBUG
  LOG_TO_FILE=1
  LOG_FILE_PATH=/srv/chat/log/chat.log
  LOG_INCLUDE_INPUT=1
  LOG_INCLUDE_OUTPUT=final
  LOG_CONTENT_MAX_CHARS=800
  LOG_REDACT_ENABLED=1
  ```

- 产生的日志示例：
  - `INFO request.input.preview | {"messages":2,"text_len":1234,"preview":"你好，我想了解…"}`
  - `DEBUG sse.content.delta.preview | {"delta_len":57,"preview":"当然可以，我们先从…"}`
  - `INFO sse.output.final.preview | {"text_len":1456,"preview":"最终文本…(截断)"}`

#### 会话级日志文件

- 开启每个会话独立文件：
  - `SESSION_LOG_ENABLED=1`
  - `SESSION_LOG_BASE_DIR=/srv/chat/log`

- 结构：在 `<BASE>/<sessionId>/` 目录下生成 `<sessionId>.log`，记录该会话的输入预览、增量预览、最终预览以及生命周期事件。

- 示例：
  ```env
  SESSION_LOG_ENABLED=1
  SESSION_LOG_BASE_DIR=/srv/chat/log
  LOG_INCLUDE_INPUT=1
  LOG_INCLUDE_OUTPUT=both
  LOG_LEVEL=DEBUG
  ```
  请求后查看：
  ```bash
  tail -n 100 /srv/chat/log/session-demo/session-demo.log
  ```

### 行流式推送（分句）

- 作用：将增量文本自动断句并逐行推送到行流服务或写入本地文件，文件名为 `sessionId`，便于下游 `/srv/voice_clone` 按行消费。

- 配置：
  - `VOICE_LINE_BASE_URL` 行流HTTP服务基础地址（如 `http://127.0.0.1:8015`）；留空则使用本地写入。
  - `VOICE_LINE_USE_MOCK=1` 仅写本地文件（默认开启便于开发）。
  - `VOICE_LINE_DIR=/srv/chat/log` 本地文件目录。

- 本地写入结构：在 `<VOICE_LINE_DIR>/<sessionId>/<sessionId>.lines` 文件中按行追加。

- 验证：
  ```bash
  # 开启内容预览与行流本地写入
  export LOG_INCLUDE_OUTPUT=both
  export VOICE_LINE_USE_MOCK=1
  export VOICE_LINE_DIR=/srv/chat/log
  uvicorn app.main:app --host 0.0.0.0 --port 8084

  # 发起请求
  curl -N -H "Accept: text/event-stream" -H "Content-Type: application/json" \
    -d '{"model":"gpt-4o-mini","input":"请分点说明今天的安排。","sessionId":"session-demo"}' \
    http://localhost:8084/chat/stream

  # 查看分句文件
  cat /srv/chat/log/session-demo/session-demo.lines
  ```

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