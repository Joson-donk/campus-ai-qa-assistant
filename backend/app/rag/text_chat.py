"""对话模型调用（FR-B2）。

使用 OpenAI SDK 调用**任意 OpenAI 兼容**的对话模型，默认 DeepSeek（``deepseek-chat``），
统一以生成器形式产出增量文本，天然支持流式与非流式两种消费方式。
同样内置离线 :class:`MockChatModel`，保证无 Key 也能跑通端到端问答。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "deepseek-chat"
DEFAULT_CHAT_BASE_URL = "https://api.deepseek.com/v1"

Message = Dict[str, str]


class ChatModelError(RuntimeError):
    """对话模型调用失败。"""


class BaseChatModel:
    """对话模型基类。"""

    name = "base"
    model: str = ""

    def stream(self, messages: Sequence[Message], **kwargs) -> Iterator[str]:
        raise NotImplementedError

    def complete(self, messages: Sequence[Message], **kwargs) -> str:
        return "".join(self.stream(messages, **kwargs))


class OpenAICompatChatModel(BaseChatModel):
    """OpenAI SDK 兼容的对话模型（DeepSeek / 百炼 / OpenAI / 本地 vLLM 均可）。"""

    name = "openai-compatible"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_CHAT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        top_p: float = 0.9,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ChatModelError("缺少依赖 openai，请执行 pip install openai") from exc

        api_key = api_key or os.getenv("CHAT_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ChatModelError("未配置对话模型 API Key（CHAT_API_KEY / DEEPSEEK_API_KEY）")

        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.top_p = float(top_p)
        self.max_retries = max(0, int(max_retries))
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("CHAT_BASE_URL") or DEFAULT_CHAT_BASE_URL,
            timeout=timeout,
            max_retries=0,
        )

    def stream(self, messages: Sequence[Message], **kwargs) -> Iterator[str]:
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": list(messages),
            "temperature": float(kwargs.get("temperature", self.temperature)),
            "max_tokens": int(kwargs.get("max_tokens", self.max_tokens)),
            "top_p": float(kwargs.get("top_p", self.top_p)),
            "stream": True,
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(**payload)
                for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if piece:
                        yield piece
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retries:
                    wait = 1.5 ** attempt
                    logger.warning("对话模型失败（第 %s 次），%.1fs 后重试: %s", attempt + 1, wait, exc)
                    time.sleep(wait)
        raise ChatModelError(f"对话模型调用失败: {last_error}") from last_error


class MockChatModel(BaseChatModel):
    """离线对话模型（仅用于开发/单测/无 Key 演示）。

    它不做任何「生成」，只是把命中的材料**原样摘录**并标注引用编号，
    这样即使没有 API Key，也能验证「检索 → 拼提示词 → 流式输出 → 引用展示」整条链路。
    """

    name = "mock"

    def __init__(self, model: str = "mock-chat", chunk_size: int = 12) -> None:
        self.model = model
        self.chunk_size = max(1, int(chunk_size))

    @staticmethod
    def _parse_context(user_prompt: str) -> List[str]:
        blocks: List[str] = []
        current: List[str] = []
        for line in user_prompt.splitlines():
            if line.startswith("【材料"):
                if current:
                    blocks.append("\n".join(current).strip())
                current = []
            elif line.startswith("【问题】"):
                break
            elif current is not None:
                current.append(line)
        if current:
            blocks.append("\n".join(current).strip())
        return [b for b in blocks if b]

    def stream(self, messages: Sequence[Message], **kwargs) -> Iterator[str]:
        user_prompt = ""
        for message in reversed(list(messages)):
            if message.get("role") == "user":
                user_prompt = message.get("content", "")
                break

        blocks = self._parse_context(user_prompt)
        if not blocks or "（无相关材料）" in user_prompt:
            answer = "知识库中未找到相关依据，无法回答该问题。请补充相关政策文档后重试。"
        else:
            lines = ["（离线 Mock 模式）依据知识库材料，摘录如下："]
            for i, block in enumerate(blocks[:3], start=1):
                excerpt = block.split("\n", 1)[-1].strip()
                excerpt = excerpt[:160] + ("…" if len(excerpt) > 160 else "")
                lines.append(f"{i}. {excerpt}【材料{i}】")
            lines.append("如需正式答案，请在 .env 中配置 CHAT_API_KEY 后重启服务。")
            answer = "\n".join(lines)

        for i in range(0, len(answer), self.chunk_size):
            yield answer[i : i + self.chunk_size]


def build_chat_model(
    provider: str = "deepseek",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    allow_mock: bool = True,
) -> BaseChatModel:
    """对话模型工厂：``provider="mock"`` 或缺 Key 时降级为离线模型。"""
    provider = (provider or "deepseek").strip().lower()
    if provider in ("mock", "offline", "fake"):
        logger.warning("使用 MockChatModel（离线），答案由材料摘录拼接而成")
        return MockChatModel()

    key = api_key or os.getenv("CHAT_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not key:
        if not allow_mock:
            raise ChatModelError("未配置 CHAT_API_KEY / DEEPSEEK_API_KEY")
        logger.warning("未检测到对话模型 API Key，自动降级为 MockChatModel")
        return MockChatModel()

    return OpenAICompatChatModel(
        api_key=key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def messages_to_text(messages: Iterable[Message]) -> str:
    """调试用：把 messages 打印成可读文本。"""
    return "\n".join(f"[{m.get('role')}] {m.get('content')}" for m in messages)