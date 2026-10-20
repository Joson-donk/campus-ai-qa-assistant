"""Pydantic 请求 / 响应模型（FR-C1：禁止裸 dict 拼装返回）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# 问答（模块 B）
# ---------------------------------------------------------------------------
class ChatMessageIn(BaseModel):
    """多轮对话历史中的一条消息（FR-B5）。"""

    role: Literal["user", "assistant"] = Field(..., description="角色")
    content: str = Field(..., min_length=1, max_length=8000, description="消息内容")


class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: Optional[str] = Field(None, max_length=64, description="会话 ID，不传则由服务端生成")
    history: List[ChatMessageIn] = Field(default_factory=list, description="多轮对话历史（不含本次问题）")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="检索条数，默认取服务端配置")
    stream: bool = Field(True, description="true=SSE 流式；false=一次性返回 JSON（便于 Swagger 自测）")

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空白字符")
        return value


class HitOut(BaseModel):
    """命中的原文片段（FR-B4）。"""

    model_config = ConfigDict(from_attributes=True)

    index: int = Field(..., description="材料编号，与答案中的【n】对应")
    id: str = Field(..., description="向量库中的块 ID")
    score: float = Field(..., description="余弦相似度")
    text: str = Field(..., description="命中的原文片段")
    source: str = Field(..., description="来源文件名")
    page: Optional[str] = Field(None, description="页码或章节")
    doc_id: Optional[str] = None
    chunk_index: int = 0


class ChatTiming(BaseModel):
    retrieve_ms: int = 0
    first_token_ms: Optional[int] = None
    total_ms: int = 0


class ChatResult(BaseModel):
    """非流式模式的完整结果。"""

    session_id: str
    answer: str
    refused: bool = Field(..., description="是否因缺少依据而拒答")
    hits: List[HitOut] = Field(default_factory=list)
    raw_hits: List[HitOut] = Field(default_factory=list, description="未经阈值过滤的 Top-K")
    score_threshold: float = 0.0
    timing: ChatTiming = Field(default_factory=ChatTiming)
    model: str = ""
    log_id: Optional[int] = Field(None, description="写入 MySQL 的问答日志主键")


class ChatStreamEvent(BaseModel):
    """SSE 单条事件的 data 载荷。"""

    type: Literal["retrieval", "delta", "done", "error"] = Field(..., description="事件类型")
    session_id: str = ""
    content: Optional[str] = Field(None, description="type=delta 时的增量文本")
    hits: List[HitOut] = Field(default_factory=list)
    raw_hits: List[HitOut] = Field(default_factory=list)
    answer: Optional[str] = None
    raw_answer: Optional[str] = Field(None, description="规范化之前的原始答案，便于排查引用编号问题")
    dropped_citations: Optional[int] = Field(None, description="被剔除的悬空引用编号数量")
    remapped_citations: Optional[int] = Field(None, description="由条款号纠正为材料序号的引用数量")
    refused: Optional[bool] = None
    timing: Optional[ChatTiming] = None
    model: Optional[str] = None
    log_id: Optional[int] = None
    message: Optional[str] = Field(None, description="type=error 时的错误信息")


# ---------------------------------------------------------------------------
# 知识库（模块 A）
# ---------------------------------------------------------------------------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    filename: str
    suffix: str = ""
    chunk_count: int = 0
    vector_chunk_count: int = 0
    consistent: bool = True
    page_count: int = 0
    char_count: int = 0
    size_bytes: int = 0
    strategy: str = ""
    status: str = "ready"
    content_hash: str = ""
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UploadResult(BaseModel):
    """POST /api/kb/upload 的业务数据。"""

    document: DocumentOut
    replaced: bool = Field(False, description="是否因内容哈希相同而覆盖了旧数据（FR-A5）")
    chunk_count: int = 0
    strategy: str = ""
    max_length: int = 0
    chunk_overlap: int = 0
    elapsed_ms: int = 0


class KbStats(BaseModel):
    """GET /api/kb/stats 的业务数据。"""

    doc_count: int = 0
    chunk_count: int = 0
    vector_backend: str = ""
    collection: str = ""
    embedding_dim: int = 0
    embedding_model: str = ""
    chunk_strategy: str = ""
    total_char_count: int = 0


# ---------------------------------------------------------------------------
# 问答日志（模块 D）
# ---------------------------------------------------------------------------
class QALogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    question: str
    answer: str
    hit_ids: List[str] = Field(default_factory=list)
    hit_count: int = 0
    top_score: float = 0.0
    refused: bool = False
    retrieve_ms: int = 0
    first_token_ms: Optional[int] = None
    total_ms: int = 0
    model: str = ""
    strategy: str = ""
    created_at: Optional[datetime] = None


class HealthOut(BaseModel):
    status: str = "ok"
    app: str = ""
    env: str = ""
    vector_backend: str = ""
    database: str = ""
    embedding_model: str = ""
    chat_model: str = ""
    warnings: List[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)