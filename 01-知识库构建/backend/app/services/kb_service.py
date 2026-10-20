"""知识库服务（模块 A）：解析 → 分块 → 嵌入 → 入库 → 登记。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import Settings
from ..db import repository
from ..db.models import Document
from ..exceptions import AppError, NotFoundError, ValidationError
from ..rag.loader import SUPPORTED_SUFFIXES, DocumentParseError, file_sha256, load_document
from ..rag.text_index import VectorRecord
from ..rag.text_split import VALID_STRATEGIES, TextChunk, split_text
from .container import Container

logger = logging.getLogger(__name__)

MAX_STORED_TEXT_CHARS = 20000


@dataclass
class IngestResult:
    document: Document
    chunks: List[TextChunk]
    replaced: bool
    elapsed_ms: int


class KnowledgeBaseService:
    """对上层 API 暴露的知识库能力。"""

    def __init__(self, container: Container) -> None:
        self.container = container
        self.settings: Settings = container.settings

    # -- 入库 -----------------------------------------------------------
    def ingest_file(
        self,
        session: Session,
        *,
        path: Path,
        filename: str,
        strategy: Optional[str] = None,
        max_length: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> IngestResult:
        started = time.perf_counter()
        strategy = (strategy or self.settings.chunk_strategy).strip().lower()
        if strategy not in VALID_STRATEGIES:
            raise ValidationError(f"不支持的分块策略: {strategy}，可选 {list(VALID_STRATEGIES)}")
        max_length = int(max_length or self.settings.chunk_max_length)
        chunk_overlap = int(chunk_overlap if chunk_overlap is not None else self.settings.chunk_overlap)
        if not 16 <= max_length <= 8000:
            raise ValidationError("max_length 需在 16 ~ 8000 之间")
        if not 0 <= chunk_overlap < max_length:
            raise ValidationError("chunk_overlap 需满足 0 <= chunk_overlap < max_length")

        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValidationError(f"不支持的文件类型: {suffix or '(无扩展名)'}，仅支持 {list(SUPPORTED_SUFFIXES)}")

        content_hash = file_sha256(path)
        doc_id = content_hash[:16]

        try:
            pages = load_document(path)
        except DocumentParseError as exc:
            raise AppError(str(exc), code=422, http_status=422) from exc

        chunks: List[TextChunk] = []
        for page in pages:
            for chunk in split_text(
                page.text,
                strategy=strategy,
                max_length=max_length,
                chunk_overlap=chunk_overlap,
                page=page.page,
            ):
                chunk.chunk_index = len(chunks)  # 全文档连续编号（FR-A4）
                chunks.append(chunk)

        if not chunks:
            raise AppError("文档解析后没有可用文本块，请检查文件内容", code=422, http_status=422)

        # FR-A5：同内容重复上传 → 先按 doc_id 清掉旧向量，保证不产生重复块
        existing = repository.get_document_by_doc_id(session, doc_id)
        replaced = existing is not None
        removed = self.container.store.delete_by_doc(doc_id)
        if removed:
            logger.info("覆盖旧数据：doc_id=%s 删除 %s 个旧块", doc_id, removed)

        texts = [c.text[:MAX_STORED_TEXT_CHARS] for c in chunks]
        vectors = self.container.embedder.embed_documents(texts)
        if len(vectors) != len(chunks):
            raise AppError(
                f"嵌入结果数量({len(vectors)})与分块数量({len(chunks)})不一致", code=502, http_status=502
            )

        records = [
            VectorRecord(
                id=f"{doc_id}:{chunk.chunk_index:05d}",
                doc_id=doc_id,
                source=filename,
                page=chunk.page,
                chunk_index=chunk.chunk_index,
                text=chunk.text[:MAX_STORED_TEXT_CHARS],
                vector=vector,
                strategy=strategy,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self.container.store.upsert(records)

        doc = Document(
            doc_id=doc_id,
            filename=filename,
            suffix=suffix,
            content_hash=content_hash,
            size_bytes=path.stat().st_size,
            page_count=len(pages),
            char_count=sum(len(c.text) for c in chunks),
            chunk_count=len(chunks),
            strategy=strategy,
            chunk_max_length=max_length,
            chunk_overlap=chunk_overlap,
            status="ready",
        )
        saved = repository.upsert_document(session, doc)
        session.commit()

        elapsed = int((time.perf_counter() - started) * 1000)
        logger.info("入库完成: %s -> %s 块, 耗时 %sms", filename, len(chunks), elapsed)
        return IngestResult(document=saved, chunks=chunks, replaced=replaced, elapsed_ms=elapsed)

    # -- 查询 -----------------------------------------------------------
    def list_documents(self, session: Session, keyword: str = "") -> List[Dict[str, Any]]:
        """文档列表（FR：含分块数、入库时间），并用向量库实际块数做交叉校验。"""
        docs = repository.list_documents(session, keyword)
        actual = {item["doc_id"]: item for item in self.container.store.list_documents()}
        out: List[Dict[str, Any]] = []
        for doc in docs:
            real = actual.get(doc.doc_id, {})
            real_count = int(real.get("chunk_count", 0) or 0)
            out.append(
                {
                    "doc_id": doc.doc_id,
                    "filename": doc.filename,
                    "suffix": doc.suffix,
                    "chunk_count": doc.chunk_count,
                    "vector_chunk_count": real_count,
                    "consistent": real_count == doc.chunk_count,
                    "page_count": doc.page_count,
                    "char_count": doc.char_count,
                    "size_bytes": doc.size_bytes,
                    "strategy": doc.strategy,
                    "status": doc.status,
                    "content_hash": doc.content_hash,
                    "error_message": doc.error_message,
                    "created_at": doc.created_at,
                    "updated_at": doc.updated_at,
                }
            )
        return out

    def stats(self, session: Session) -> Dict[str, Any]:
        db_stats = repository.document_stats(session)
        return {
            "doc_count": db_stats["doc_count"],
            "chunk_count": self.container.store.count(),
            "db_chunk_count": db_stats["chunk_count"],
            "total_char_count": db_stats["char_count"],
            "vector_backend": self.container.store.name,
            "collection": self.container.store.collection,
            "embedding_dim": self.container.store.dim,
            "embedding_model": getattr(self.container.embedder, "model", self.container.embedder.name),
            "chunk_strategy": self.settings.chunk_strategy,
        }

    # -- 删除 -----------------------------------------------------------
    def delete_document(self, session: Session, doc_id: str) -> Dict[str, Any]:
        doc = repository.get_document_by_doc_id(session, doc_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {doc_id}")
        removed = self.container.store.delete_by_doc(doc_id)
        repository.delete_document(session, doc_id)
        session.commit()
        logger.info("删除文档 %s（%s）：清除 %s 个向量", doc.filename, doc_id, removed)
        return {"doc_id": doc_id, "filename": doc.filename, "removed_chunks": removed}