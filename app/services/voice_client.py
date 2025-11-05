import os
import base64
from typing import Iterable, Dict, Any, Optional

from app.utils.retry import retry_with_backoff
from dotenv import dotenv_values


class VoiceMockStream:
    """
    语音克隆模拟流：将给定文本转换为若干Base64片段，模拟音频流。

    说明：
        - 仅用于本地开发与无真实服务时的验证（通过 VOICE_USE_MOCK=1 开启）。
    """

    def __init__(self, text: str, chunk_size: int = 10):
        self.text = text
        self.chunk_size = chunk_size

    def __iter__(self):
        return self.events()

    def events(self) -> Iterable[Dict[str, Any]]:
        data = self.text.encode("utf-8")
        # 将文本按 chunk_size 切片并进行 base64 编码，模拟音频数据块
        for i in range(0, len(data), self.chunk_size):
            chunk = data[i : i + self.chunk_size]
            b64 = base64.b64encode(chunk).decode("ascii")
            yield {"b64": b64}


class VoiceClient:
    """
    语音克隆客户端，封装与外部声音克隆服务的交互，支持流式合成。

    环境变量：
        VOICE_CLONE_BASE_URL: 服务基础地址
        VOICE_CLONE_API_KEY: 访问密钥
        VOICE_USE_MOCK: 为 '1' 时使用模拟流

    方法：
        synthesize_stream(text, session_id, voice_id?, audio_format): 返回可迭代对象，产生 base64 音频块
    """

    def __init__(self):
        """
        初始化语音客户端，优先从项目根目录的 .env 加载配置。

        加载顺序与优先级：
            1) 读取 /srv/chat/.env（通过相对路径定位项目根）
            2) 若 .env 未提供某项，再回退到进程环境变量 os.environ

        关键变量：
            - VOICE_CLONE_BASE_URL: 语音服务基础地址
            - VOICE_CLONE_API_KEY: 语音服务密钥（可选）
            - VOICE_USE_MOCK: 为 '1' 时使用本地模拟流
            - USE_MOCK: 若为 '1'，也强制使用模拟（便于测试统一控制）
        """
        # 通过文件读取 .env，而不是仅依赖进程环境变量
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env_path = os.path.join(project_root, ".env")
        env_vars: Dict[str, str] = {}
        try:
            env_vars = dotenv_values(env_path) or {}
        except Exception:
            env_vars = {}

        # 优先使用 .env 的值，其次回退到进程环境变量
        self.base_url = env_vars.get("VOICE_CLONE_BASE_URL") or os.environ.get("VOICE_CLONE_BASE_URL", "")
        self.api_key = env_vars.get("VOICE_CLONE_API_KEY") or os.environ.get("VOICE_CLONE_API_KEY", "")
        # 允许测试通过通用 USE_MOCK=1 强制启用模拟，即使 .env 中 VOICE_USE_MOCK=0
        self.use_mock = (
            (env_vars.get("VOICE_USE_MOCK") == "1")
            or (os.environ.get("VOICE_USE_MOCK") == "1")
            or (os.environ.get("USE_MOCK") == "1")
        )

    @retry_with_backoff()
    def synthesize_stream(self, text: str, session_id: str, voice_id: Optional[str] = None, audio_format: str = "mp3"):
        """
        发起流式语音合成请求。

        输入：
            text: 要合成的文本
            session_id: 语音会话ID（用于服务端维护流、中断/续传等）
            voice_id: 音色ID或模板名（可选）
            audio_format: 音频格式（mp3/wav等），默认 mp3

        输出：
            可迭代对象：每次迭代返回字典 {"b64": "..."}

        关键逻辑：
            - 若 VOICE_USE_MOCK=1，则返回模拟流。
            - 否则调用 {base_url}/api/tts/stream（JSON请求，字节流响应），将字节块转为 base64 输出。
            - 请求体字段按 TTS 服务 OpenAPI：text、session_id、voice_type（可选）、save_path（可选）。
            - 响应必须为音频内容类型（content-type 以 audio/ 开头），否则抛出异常。
        """
        # 运行时再次评估是否使用模拟，避免实例化时环境变量尚未设置导致误用真实服务
        runtime_mock = (
            self.use_mock
            or (os.environ.get("USE_MOCK") == "1")
            or (os.environ.get("VOICE_USE_MOCK") == "1")
        )
        if runtime_mock or not self.base_url:
            return VoiceMockStream(text)

        import httpx

        # 适配你提供的接口：POST {base}/api/tts/stream，JSON体为 {text, session_id, voice_id?, format?}
        with httpx.Client(timeout=None) as client:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/octet-stream",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            # 按 /api/tts/stream 的 schema 组织请求体
            payload = {"text": text, "session_id": session_id}
            if voice_id:
                # 将上游的 voice_id 映射为 TTS 服务的 voice_type
                payload["voice_type"] = voice_id
            # 可选：允许服务端保存副本；此处默认不传递 save_path
            url = f"{self.base_url.rstrip('/')}/api/tts/stream"
            with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                # 校验返回的内容类型是否为音频
                ct = resp.headers.get("content-type", "")
                if not ct.startswith("audio/"):
                    # 读取部分错误内容用于诊断
                    preview = ""
                    try:
                        raw = resp.read()[:256]
                        try:
                            preview = raw.decode("utf-8", "ignore")
                        except Exception:
                            preview = str(raw)
                    except Exception:
                        preview = ""
                    raise RuntimeError(f"TTS responded non-audio content-type: {ct}, status={resp.status_code}, preview={preview}")
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    b64 = base64.b64encode(chunk).decode("ascii")
                    yield {"b64": b64}