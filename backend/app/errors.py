import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)
HTTP_ERROR_MESSAGES = {
    400: ("bad_request", "请求无效"),
    401: ("unauthorized", "请先登录"),
    403: ("forbidden", "没有执行此操作的权限"),
    404: ("not_found", "请求的资源不存在"),
    405: ("method_not_allowed", "请求方法不受支持"),
    409: ("conflict", "请求与当前资源状态冲突"),
    422: ("validation_error", "请求参数不合法"),
    501: ("not_implemented", "该接口的实现将在后续任务完成"),
    503: ("service_unavailable", "依赖服务不可用"),
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: Sequence[dict[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code, message = HTTP_ERROR_MESSAGES.get(
            exc.status_code,
            ("request_failed", "请求未能完成"),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": _error_body(code, message)},
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": _error_body(exc.code, exc.message, exc.field_errors)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        field_errors = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": _error_body(
                    "validation_error",
                    "请求参数不合法",
                    field_errors,
                )
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled API exception type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": _error_body("internal_error", "服务器内部错误")},
        )


def _error_body(
    code: str,
    message: str,
    field_errors: Sequence[dict[str, str]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if field_errors:
        body["field_errors"] = list(field_errors)
    return body
