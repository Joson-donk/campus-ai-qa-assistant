"""问答日志接口（模块 C / D）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import repository
from ..db.session import get_db
from ..exceptions import NotFoundError
from ..response import ApiResponse, PageData, build_page
from ..schemas import QALogOut

router = APIRouter(prefix="/api", tags=["问答日志"])


@router.get(
    "/logs",
    response_model=ApiResponse[PageData[QALogOut]],
    summary="问答日志分页查询",
    description="支持按会话 ID 与关键词过滤，返回问题、答案、命中块、耗时等完整字段（FR-D1）。",
)
def list_logs(
    session: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    session_id: str = Query("", description="按会话 ID 精确过滤"),
    keyword: str = Query("", description="在问题/答案中模糊搜索"),
):
    logs, total = repository.list_qa_logs(
        session, page=page, page_size=page_size, session_id=session_id, keyword=keyword
    )
    items = [repository.qa_log_to_dict(log) for log in logs]
    return ApiResponse.ok(build_page(items, page, page_size, total))


@router.get(
    "/logs/{log_id}",
    response_model=ApiResponse[QALogOut],
    summary="查询单条问答日志",
)
def get_log(log_id: int, session: Session = Depends(get_db)):
    from sqlalchemy import select
    from ..db.models import QALog

    log = session.execute(select(QALog).where(QALog.id == log_id)).scalar_one_or_none()
    if log is None:
        raise NotFoundError(f"日志不存在: {log_id}")
    return ApiResponse.ok(repository.qa_log_to_dict(log))