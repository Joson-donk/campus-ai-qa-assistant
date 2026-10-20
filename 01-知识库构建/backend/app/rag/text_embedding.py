"""文本嵌入模块（FR-A3）。

默认使用阿里云百炼 ``text-embedding-v4``（1024 维，OpenAI 兼容接口）。
为了让项目在**没有 API Key / 断网**的环境下依然能跑通全链路（开发、单测、CI），
额外内置一个确定性的 :class:`MockEmbedder`：它基于字符 n-gram 哈希生成向量，
词面重合度越高余弦相似度越高，足以验证检索链路是否正确。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
from typing import List, Sequence

logger = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "text-embedding-v4"
DEFAULT_EMBED_DIM = 1024
DEFAULT_EMBED_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

_ASCII_WORD = re.compile(r"[a-zA-Z0-9]+")


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """手算余弦相似度（课件要求：先手算，再换 Milvus）。"""
    if len(a) != len(b):
        raise ValueError(f"向量维度不一致: {len(a)} vs {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class BaseEmbedder:
    """嵌入器基类。"""

    dim: int = DEFAULT_EMBED_DIM
    name: str = "base"

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        vectors = self.embed_documents([text])
        return vectors[0]


class OpenAICompatEmbedder(BaseEmbedder):
    """通过 OpenAI SDK 调用任意 OpenAI 兼容的嵌入接口。"""

    name = "openai-compatible"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_EMBED_MODEL,
        dimensions: int = DEFAULT_EMBED_DIM,
        batch_size: int = 10,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少依赖 openai，请执行 pip install openai") from exc

        api_key = api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未配置嵌入模型 API Key（EMBEDDING_API_KEY / DASHSCOPE_API_KEY）")

        self.model = model
        self.dim = int(dimensions)
        self.batch_size = max(1, int(batch_size))
        self.max_retries = max(0, int(max_retries))
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("EMBEDDING_BASE_URL") or DEFAULT_EMBED_BASE_URL,
            timeout=timeout,
            max_retries=0,  # 重试自己实现，便于打印日志与退避
        )

    def _embed_batch(self, batch: Sequence[str]) -> List[List[float]]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                kwargs = {"model": self.model, "input": list(batch)}
                # text-embedding-v3/v4 支持指定输出维度
                if self.dim:
                    kwargs["dimensions"] = self.dim
                resp = self._client.embeddings.create(**kwargs)
                items = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
                return [list(item.embedding) for item in items]
            except Exception as exc:  # noqa: BLE001 - 网络/限流统一退避重试
                last_error = exc
                if attempt < self.max_retries:
                    wait = 1.5 ** attempt
                    logger.warning("嵌入请求失败（第 %s 次），%.1fs 后重试: %s", attempt + 1, wait, exc)
                    time.sleep(wait)
        raise RuntimeError(f"嵌入模型调用失败: {last_error}") from last_error

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        cleaned = [(t or "").strip() or "（空文本）" for t in texts]
        vectors: List[List[float]] = []
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch))
            logger.debug("嵌入进度 %s/%s", min(start + self.batch_size, len(cleaned)), len(cleaned))
        if vectors and self.dim and len(vectors[0]) != self.dim:
            logger.warning("嵌入维度为 %s，与配置的 %s 不一致", len(vectors[0]), self.dim)
            self.dim = len(vectors[0])
        return vectors


class MockEmbedder(BaseEmbedder):
    """离线确定性伪嵌入器（仅用于开发/单测/无 Key 演示）。"""

    name = "mock"

    def __init__(self, dim: int = DEFAULT_EMBED_DIM, ngram: int = 2, seed: str = "campus-rag") -> None:
        self.dim = int(dim)
        self.ngram = max(1, int(ngram))
        self.seed = seed

    def _tokenize(self, text: str) -> List[str]:
        text = (text or "").lower()
        tokens = _ASCII_WORD.findall(text)
        han = re.findall(r"[\u4e00-\u9fff]", text)
        for i in range(len(han) - self.ngram + 1):
            tokens.append("".join(han[i : i + self.ngram]))
        tokens.extend(han)
        return tokens or ["<empty>"]

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * self.dim
        for token in self._tokenize(text):
            digest = hashlib.blake2b(
                f"{self.seed}|{token}".encode("utf-8"), digest_size=16
            ).digest()
            value = int.from_bytes(digest[:8], "little")
            idx = value % self.dim
            sign = 1.0 if (value >> 63) & 1 else -1.0
            weight = 1.0 + (int.from_bytes(digest[8:12], "little") % 100) / 100.0
            vector[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]


def build_embedder(
    provider: str = "dashscope",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = DEFAULT_EMBED_MODEL,
    dimensions: int = DEFAULT_EMBED_DIM,
    batch_size: int = 10,
    allow_mock: bool = True,
) -> BaseEmbedder:
    """嵌入器工厂。

    ``provider="mock"`` 或未配置 Key 且 ``allow_mock=True`` 时返回离线伪嵌入器，
    保证「无 Key 也能跑通全链路」。
    """
    provider = (provider or "dashscope").strip().lower()
    if provider in ("mock", "offline", "fake"):
        logger.warning("使用 MockEmbedder（离线伪嵌入），检索质量仅用于链路验证")
        return MockEmbedder(dim=dimensions)

    key = api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not key:
        if not allow_mock:
            raise RuntimeError("未配置 EMBEDDING_API_KEY / DASHSCOPE_API_KEY")
        logger.warning("未检测到嵌入模型 API Key，自动降级为 MockEmbedder（仅用于本地联调）")
        return MockEmbedder(dim=dimensions)

    return OpenAICompatEmbedder(
        api_key=key,
        base_url=base_url,
        model=model,
        dimensions=dimensions,
        batch_size=batch_size,
    )