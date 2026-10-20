"""统一响应格式 ``{"code": int, "message": str, "data": object}``（FR-C1）。"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """所有 HTTP 接口的统一返回体。"""

    code: int = Field(0, description="业务状态码，0 表示成功，非 0 表示失败")
    message: str = Field("ok", description="提示信息")
    data: Optional[T] = Field(None, description="业务数据，失败时为 null")

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, message: str = "error", code: int = 500, data: Any = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data)


class PageMeta(BaseModel):
    """分页元信息。"""

    page: int = 1
    page_size: int = 20
    total: int = 0
    total_pages: int = 0


class PageData(BaseModel, Generic[T]):
    """分页数据体。"""

    items: list[T] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)


def build_page(items: list, page: int, page_size: int, total: int) -> dict:
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": items,
        "meta": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
    }