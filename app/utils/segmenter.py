import re
from typing import List


class SentenceSegmenter:
    """
    增量断句器：按中文/英文常见终止符将流式文本增量切分为句子。

    输入/输出：
        - feed(delta: str) -> List[str]：输入增量，返回已完成的句子列表；内部保留未完成缓冲。
        - flush() -> List[str]：在流结束时调用，返回剩余未完成内容（若非空视为一句）。

    关键逻辑：
        - 终止符：包含中文全角与英文半角 `。！？!?；;` 与换行 `\n`；
        - 若遇到多个终止符连续，按实际分割；
        - 保留缓冲区，只有遇到终止符时输出完整句子。
    """

    def __init__(self):
        self.buffer = ""
        # 捕获终止符，以便保留标点在句末
        self._pat = re.compile(r"([^。！？!?；;\n]*)([。！？!?；;\n])")

    def feed(self, delta: str) -> List[str]:
        """
        输入增量并返回已完成句子列表。
        """
        out: List[str] = []
        self.buffer += delta
        i = 0
        while True:
            m = self._pat.match(self.buffer, i)
            if not m:
                break
            # 句子内容 + 终止符
            sent = (m.group(1) + m.group(2)).strip()
            if sent:
                out.append(sent)
            i = m.end()
        # 截断已消费部分
        if i:
            self.buffer = self.buffer[i:]
        return out

    def flush(self) -> List[str]:
        """
        在流结束时输出剩余缓冲（若存在）。
        """
        residual = self.buffer.strip()
        self.buffer = ""
        return [residual] if residual else []