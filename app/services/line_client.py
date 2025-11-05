import os
from typing import Iterable, Optional
import httpx


class LineClient:
    """
    行流客户端：将分句后的文本逐行推送到 `/srv/voice_clone` 服务或写入本地文件。

    环境变量：
        VOICE_LINE_BASE_URL: 行流HTTP服务基础地址（如 http://127.0.0.1:8015 ）
        VOICE_LINE_USE_MOCK: 为 '1' 时仅写入本地文件，不走HTTP
        VOICE_LINE_DIR: 本地写入目录（默认 /srv/chat/log）

    HTTP 协议约定：
        - POST {base}/api/line/stream
        - JSON: {"session_id": "...", "line": "..."}
        - 返回 200/204 即视为成功；错误抛出异常。
    """

    def __init__(self):
        self.base_url = os.environ.get("VOICE_LINE_BASE_URL", "")
        self.use_mock = (os.environ.get("VOICE_LINE_USE_MOCK") == "1") or not self.base_url
        self.dir = os.environ.get("VOICE_LINE_DIR", "/srv/chat/log")

    def send_line(self, session_id: Optional[str], line: str) -> None:
        if not session_id or not line:
            return
        if self.use_mock:
            # 写入会话文件夹下的 lines.txt
            target_dir = os.path.join(self.dir, session_id)
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, f"{session_id}.lines")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return
        # HTTP 发送
        with httpx.Client(timeout=10) as client:
            url = f"{self.base_url.rstrip('/')}/api/line/stream"
            resp = client.post(url, json={"session_id": session_id, "line": line})
            resp.raise_for_status()