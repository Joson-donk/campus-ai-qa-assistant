"""知识库管理接口（模块 C）。"""

from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db.session import get_db
from ..exceptions import NotFoundError, ValidationError
from ..rag.loader import SUPPORTED_SUFFIXES
from ..response import ApiResponse
from ..schemas import DocumentOut, KbStats, UploadResult
from ..services.kb_service import KnowledgeBaseService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb", tags=["知识库"])

_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _kb_service(request: Request) -> KnowledgeBaseService:
    return KnowledgeBaseService(request.app.state.container)


def _safe_filename(raw: Optional[str]) -> str:
    name = Path(raw or "").name.strip()
    name = _UNSAFE.sub("_", name)
    return name or f"upload-{uuid.uuid4().hex[:8]}"


@router.post(
    "/upload",
    response_model=ApiResponse[UploadResult],
    summary="上传文档并入知识库",
    description=(
        "支持 `.pdf` / `.docx` / `.txt` / `.md`。\n\n"
        "处理链路：解析纯文本 → 分块（可选 fixed / recursive）→ 嵌入 1024 维向量 → 写入向量库 → 登记到 MySQL。\n\n"
        "**FR-A5**：以文件内容 SHA-256 判定重复，同一份文档重复上传会覆盖旧块，不会产生重复数据。"
    ),
)
async def upload_document(
    request: Request,
    session: Session = Depends(get_db),
    file: UploadFile = File(..., description="待入库的文档"),
    strategy: Optional[str] = Form(None, description="分块策略：fixed / recursive，默认取服务端配置"),
    max_length: Optional[int] = Form(None, ge=16, le=8000, description="分块最大字符数"),
    chunk_overlap: Optional[int] = Form(None, ge=0, le=4000, description="相邻块重叠字符数"),
):
    started = time.perf_counter()
    service = _kb_service(request)

    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValidationError(f"不支持的文件类型: {suffix or '(无扩展名)'}，仅支持 {list(SUPPORTED_SUFFIXES)}")

    upload_root: Path = settings.resolve(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    temp_path = upload_root / f"{uuid.uuid4().hex}{suffix}"

    try:
        size = 0
        with open(temp_path, "wb") as fp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise ValidationError(f"文件超过大小上限 {settings.max_upload_mb} MB")
                fp.write(chunk)
        if size == 0:
            raise ValidationError("上传文件为空")

        result = service.ingest_file(
            session,
            path=temp_path,
            filename=filename,
            strategy=strategy,
            max_length=max_length,
            chunk_overlap=chunk_overlap,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            logger.warning("临时文件清理失败: %s", temp_path)

    doc = result.document
    data = {
        "document": {
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "suffix": doc.suffix,
            "chunk_count": doc.chunk_count,
            "vector_chunk_count": doc.chunk_count,
            "consistent": True,
            "page_count": doc.page_count,
            "char_count": doc.char_count,
            "size_bytes": doc.size_bytes,
            "strategy": doc.strategy,
            "status": doc.status,
            "content_hash": doc.content_hash,
            "error_message": doc.error_message,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
        },
        "replaced": result.replaced,
        "chunk_count": doc.chunk_count,
        "strategy": doc.strategy,
        "max_length": doc.chunk_max_length,
        "chunk_overlap": doc.chunk_overlap,
        "elapsed_ms": result.elapsed_ms or int((time.perf_counter() - started) * 1000),
    }
    message = "覆盖旧数据成功" if result.replaced else "入库成功"
    return ApiResponse.ok(data, message=message)


@router.get(
    "/list",
    response_model=ApiResponse[List[DocumentOut]],
    summary="已入库文档列表",
    description="返回文档名、分块数、入库时间等；同时给出向量库中的实际块数用于一致性校验。",
)
def list_documents(request: Request, session: Session = Depends(get_db), keyword: str = ""):
    service = _kb_service(request)
    return ApiResponse.ok(service.list_documents(session, keyword))


@router.get(
    "/stats",
    response_model=ApiResponse[KbStats],
    summary="知识库统计",
    description="文档数、总块数、向量库后端、嵌入维度等。",
)
def kb_stats(request: Request, session: Session = Depends(get_db)):
    service = _kb_service(request)
    return ApiResponse.ok(service.stats(session))


@router.delete(
    "/{doc_id}",
    response_model=ApiResponse[dict],
    summary="删除某文档及其全部向量",
)
def delete_document(doc_id: str, request: Request, session: Session = Depends(get_db)):
    if not doc_id.strip():
        raise ValidationError("doc_id 不能为空")
    service = _kb_service(request)
    data = service.delete_document(session, doc_id.strip())
    return ApiResponse.ok(data, message=f"已删除文档 {data['filename']}，清除 {data['removed_chunks']} 个向量块")