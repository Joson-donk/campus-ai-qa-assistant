"""业务异常与全局异常处理（FR-C3：绝不把堆栈抛给前端）。"""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """可预期的业务异常。"""

    http_status: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, code: int = 400, http_status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        if http_status is not None:
            self.http_status = http_status


class NotFoundError(AppError):
    http_status = status.HTTP_404_NOT_FOUND

    def __init__(self, message: str = "资源不存在", code: int = 404) -> None:
        super().__init__(message, code=code, http_status=self.http_status)


class ValidationError(AppError):
    http_status = 422

    def __init__(self, message: str = "请求参数不合法", code: int = 422) -> None:
        super().__init__(message, code=code, http_status=self.http_status)


class UpstreamError(AppError):
    """依赖的第三方服务（大模型 / 嵌入模型 / 向量库 / 数据库）异常。"""

    http_status = status.HTTP_502_BAD_GATEWAY

    def __init__(self, message: str = "上游服务异常", code: int = 502) -> None:
        super().__init__(message, code=code, http_status=self.http_status)


def _payload(code: int, message: str, data=None) -> dict:
    return {"code": code, "message": message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    """把各类异常统一转成 ``{code, message, data}`` 结构。"""

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("业务异常 %s %s -> %s", request.method, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.http_status,
            content=_payload(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            details.append({"field": ".".join(str(x) for x in err.get("loc", [])), "msg": err.get("msg")})
        message = "请求参数校验失败: " + "; ".join(f"{d['field']} {d['msg']}" for d in details[:3])
        logger.warning("参数校验失败 %s %s -> %s", request.method, request.url.path, message)
        return JSONResponse(status_code=422, content=_payload(422, message, {"errors": details}))

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(int(exc.status_code), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # 堆栈只进服务端日志，不外泄
        logger.error("未处理异常 %s %s\n%s", request.method, request.url.path, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content=_payload(500, f"服务器内部错误: {type(exc).__name__}"),
        )