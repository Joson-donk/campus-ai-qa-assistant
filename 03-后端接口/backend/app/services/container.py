"""依赖装配：把嵌入器、向量库、对话模型、RAG 链路组装成单例。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from ..config import Settings, settings as default_settings
from ..rag.text_chat import BaseChatModel, build_chat_model
from ..rag.text_embedding import BaseEmbedder, build_embedder
from ..rag.text_index import BaseVectorStore, build_vector_store
from ..rag.text_rag import RagPipeline

logger = logging.getLogger(__name__)


@dataclass
class Container:
    """应用级单例容器。"""

    settings: Settings
    embedder: BaseEmbedder
    store: BaseVectorStore
    chat_model: BaseChatModel
    pipeline: RagPipeline
    warnings: List[str]

    def describe(self) -> dict:
        return {
            "vector_backend": self.store.name,
            "collection": self.store.collection,
            "embedding_model": getattr(self.embedder, "model", self.embedder.name),
            "embedding_dim": self.store.dim,
            "chat_model": getattr(self.chat_model, "model", self.chat_model.name),
            "chunk_count": self.store.count(),
            "warnings": self.warnings,
        }

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001  # pragma: no cover
            logger.exception("关闭向量库失败")


def build_container(settings: Optional[Settings] = None) -> Container:
    cfg = settings or default_settings
    warnings: List[str] = []

    embedder = build_embedder(
        provider=cfg.embedding_provider,
        api_key=cfg.embedding_api_key or None,
        base_url=cfg.embedding_base_url or None,
        model=cfg.embedding_model,
        dimensions=cfg.embedding_dim,
        batch_size=cfg.embedding_batch_size,
        allow_mock=cfg.allow_mock_provider,
    )
    if embedder.name == "mock":
        warnings.append("嵌入模型运行在 Mock 模式：检索结果仅用于链路验证，不代表真实语义召回效果。")

    store = build_vector_store(
        backend=cfg.vector_backend,
        uri=cfg.resolve(cfg.milvus_uri).as_posix() if not cfg.milvus_uri.startswith(("http://", "https://")) else cfg.milvus_uri,
        token=cfg.milvus_token,
        root=cfg.resolve(cfg.local_store_path),
        collection=cfg.milvus_collection,
        dim=embedder.dim or cfg.embedding_dim,
    )
    if store.name == "local":
        warnings.append(
            "向量库运行在 LocalVectorStore（本地暴力检索）：Milvus Lite 官方不支持 Windows，"
            "如需 Milvus 请部署 Standalone 并设置 VECTOR_BACKEND=milvus 与 MILVUS_URI。"
        )

    chat_model = build_chat_model(
        provider=cfg.chat_provider,
        api_key=cfg.chat_api_key or None,
        base_url=cfg.chat_base_url or None,
        model=cfg.chat_model,
        temperature=cfg.chat_temperature,
        max_tokens=cfg.chat_max_tokens,
        allow_mock=cfg.allow_mock_provider,
    )
    if chat_model.name == "mock":
        warnings.append("对话模型运行在 Mock 模式：答案为材料摘录拼接，配置 CHAT_API_KEY 后即为真实生成。")

    pipeline = RagPipeline(
        embedder=embedder,
        store=store,
        chat_model=chat_model,
        top_k=cfg.rag_top_k,
        score_threshold=cfg.rag_score_threshold,
        max_context_chars=cfg.rag_max_context_chars,
        max_history_messages=cfg.rag_history_messages,
    )

    for warning in warnings:
        logger.warning(warning)

    return Container(
        settings=cfg,
        embedder=embedder,
        store=store,
        chat_model=chat_model,
        pipeline=pipeline,
        warnings=warnings,
    )