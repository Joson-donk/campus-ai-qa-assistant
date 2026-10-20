"""数据访问层：文档登记表与问答日志的 CRUD。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .models import Document, QALog


# ---------------------------------------------------------------------------
# 文档
# ---------------------------------------------------------------------------
def get_document_by_doc_id(session: Session, doc_id: str) -> Optional[Document]:
    return session.execute(select(Document).where(Document.doc_id == doc_id)).scalar_one_or_none()


def get_document_by_hash(session: Session, content_hash: str) -> Optional[Document]:
    return session.execute(
        select(Document).where(Document.content_hash == content_hash).order_by(Document.id.desc())
    ).scalars().first()


def upsert_document(session: Session, doc: Document) -> Document:
    existing = get_document_by_doc_id(session, doc.doc_id)
    if existing is None:
        session.add(doc)
        session.flush()
        return doc
    for field in (
        "filename",
        "suffix",
        "content_hash",
        "size_bytes",
        "page_count",
        "char_count",
        "chunk_count",
        "strategy",
        "chunk_max_length",
        "chunk_overlap",
        "status",
        "error_message",
    ):
        setattr(existing, field, getattr(doc, field))
    existing.updated_at = datetime.now()
    session.flush()
    return existing


def list_documents(session: Session, keyword: str = "") -> List[Document]:
    stmt = select(Document).order_by(Document.created_at.desc(), Document.id.desc())
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Document.filename.like(like), Document.doc_id.like(like)))
    return list(session.execute(stmt).scalars().all())


def delete_document(session: Session, doc_id: str) -> bool:
    result = session.execute(delete(Document).where(Document.doc_id == doc_id))
    return (result.rowcount or 0) > 0


def document_stats(session: Session) -> Dict[str, int]:
    row = session.execute(
        select(func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0)).where(
            Document.status == "ready"
        )
    ).one()
    char_row = session.execute(
        select(func.coalesce(func.sum(Document.char_count), 0)).where(Document.status == "ready")
    ).scalar_one()
    return {"doc_count": int(row[0] or 0), "chunk_count": int(row[1] or 0), "char_count": int(char_row or 0)}


# ---------------------------------------------------------------------------
# 问答日志
# ---------------------------------------------------------------------------
def create_qa_log(
    session: Session,
    *,
    session_id: str,
    question: str,
    answer: str,
    hit_ids: Sequence[str],
    hit_count: int = 0,
    top_score: float = 0.0,
    refused: bool = False,
    retrieve_ms: int = 0,
    first_token_ms: Optional[int] = None,
    total_ms: int = 0,
    model: str = "",
    strategy: str = "",
) -> QALog:
    log = QALog(
        session_id=session_id,
        question=question,
        answer=answer,
        hit_ids=json.dumps(list(hit_ids), ensure_ascii=False),
        hit_count=int(hit_count),
        top_score=float(top_score),
        refused=bool(refused),
        retrieve_ms=int(retrieve_ms),
        first_token_ms=first_token_ms,
        total_ms=int(total_ms),
        model=model,
        strategy=strategy,
    )
    session.add(log)
    session.flush()
    return log


def parse_hit_ids(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return [str(v) for v in value] if isinstance(value, list) else []
    except (ValueError, TypeError):
        return [part for part in raw.split(",") if part]


def list_qa_logs(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    session_id: str = "",
    keyword: str = "",
) -> Tuple[List[QALog], int]:
    stmt = select(QALog)
    count_stmt = select(func.count(QALog.id))
    if session_id:
        stmt = stmt.where(QALog.session_id == session_id)
        count_stmt = count_stmt.where(QALog.session_id == session_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(QALog.question.like(like), QALog.answer.like(like)))
        count_stmt = count_stmt.where(or_(QALog.question.like(like), QALog.answer.like(like)))

    total = int(session.execute(count_stmt).scalar_one() or 0)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    stmt = stmt.order_by(QALog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    return list(session.execute(stmt).scalars().all()), total


def qa_log_to_dict(log: QALog) -> Dict[str, Any]:
    return {
        "id": log.id,
        "session_id": log.session_id,
        "question": log.question,
        "answer": log.answer,
        "hit_ids": parse_hit_ids(log.hit_ids),
        "hit_count": log.hit_count,
        "top_score": round(float(log.top_score or 0.0), 6),
        "refused": bool(log.refused),
        "retrieve_ms": log.retrieve_ms,
        "first_token_ms": log.first_token_ms,
        "total_ms": log.total_ms,
        "model": log.model,
        "strategy": log.strategy,
        "created_at": log.created_at,
    }