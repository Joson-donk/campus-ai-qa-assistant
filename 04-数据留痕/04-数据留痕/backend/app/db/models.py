"""ORM 模型（FR-D2：使用 SQLAlchemy 建模，业务代码中不出现拼接 SQL）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有表的基类。"""


class Document(Base):
    """知识库文档登记表（FR-A4 / FR-A5）。"""

    __tablename__ = "kb_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="内容哈希派生的业务主键")
    filename: Mapped[str] = mapped_column(String(255), comment="原始文件名")
    suffix: Mapped[str] = mapped_column(String(16), default="", comment="扩展名")
    content_hash: Mapped[str] = mapped_column(String(64), index=True, comment="文件内容 SHA-256")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0, comment="页数/章节数")
    char_count: Mapped[int] = mapped_column(Integer, default=0, comment="正文字符数")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="入库分块数")
    strategy: Mapped[str] = mapped_column(String(32), default="recursive", comment="分块策略")
    chunk_max_length: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=64)
    status: Mapped[str] = mapped_column(String(16), default="ready", index=True, comment="ready/failed")
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document {self.doc_id} {self.filename} chunks={self.chunk_count}>"


class QALog(Base):
    """问答日志表（FR-D1）。"""

    __tablename__ = "qa_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, comment="会话 ID")
    question: Mapped[str] = mapped_column(Text, comment="用户问题")
    answer: Mapped[str] = mapped_column(Text, comment="模型答案")
    hit_ids: Mapped[str] = mapped_column(Text, default="", comment="命中 chunk 的 ID 列表(JSON)")
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    top_score: Mapped[float] = mapped_column(Float, default=0.0, comment="最高相似度")
    refused: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否拒答")
    retrieve_ms: Mapped[int] = mapped_column(Integer, default=0, comment="检索耗时")
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="首字延迟")
    total_ms: Mapped[int] = mapped_column(Integer, default=0, comment="总耗时")
    model: Mapped[str] = mapped_column(String(64), default="")
    strategy: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QALog {self.id} session={self.session_id} refused={self.refused}>"