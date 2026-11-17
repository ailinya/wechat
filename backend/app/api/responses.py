"""Reusable OpenAPI response documentation for the common error contract.

These helpers only describe responses in the generated schema; runtime error
behaviour is produced by the handlers in ``app.errors``. Keeping examples here
makes the success/failure contract visible in /openapi.json for client codegen.
"""

from __future__ import annotations

from typing import Any

from app.schemas.common import ErrorEnvelope

FIELD_ERROR_EXAMPLE = {
    "error": {
        "code": "validation_error",
        "message": "请求参数不合法",
        "field_errors": [{"field": "page", "message": "必须大于等于 1"}],
    }
}


def _error_example(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


ERROR_EXAMPLES: dict[int, dict[str, Any]] = {
    400: _error_example("bad_request", "请求无效"),
    401: _error_example("unauthorized", "请先登录"),
    403: _error_example("forbidden", "没有执行此操作的权限"),
    404: _error_example("not_found", "请求的资源不存在"),
    409: _error_example("conflict", "请求与当前资源状态冲突"),
    422: FIELD_ERROR_EXAMPLE,
    503: _error_example("service_unavailable", "依赖服务暂不可用"),
}


def error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    """Build an OpenAPI ``responses`` mapping for the given status codes."""
    documented: dict[int, dict[str, Any]] = {}
    for code in status_codes:
        documented[code] = {
            "model": ErrorEnvelope,
            "description": ERROR_EXAMPLES[code]["error"]["message"],
            "content": {
                "application/json": {
                    "example": ERROR_EXAMPLES[code],
                }
            },
        }
    return documented


NOT_IMPLEMENTED = {
    501: {
        "model": ErrorEnvelope,
        "description": "接口契约已定义，实现将在任务 1.6 完成",
        "content": {
            "application/json": {
                "example": _error_example(
                    "not_implemented", "该接口的实现将在后续任务完成"
                )
            }
        },
    }
}


IDEMPOTENCY_CONFLICT_EXAMPLE = {
    "error": {
        "code": "idempotency_conflict",
        "message": "该幂等键已被用于不同的请求内容",
    }
}


def idempotency_conflict_response() -> dict[str, Any]:
    """OpenAPI description for the 409 raised when an Idempotency-Key is
    reused with a different request fingerprint (enforced by task 2.5)."""
    return {
        "model": ErrorEnvelope,
        "description": "同一作用域内幂等键被不同内容复用",
        "content": {"application/json": {"example": IDEMPOTENCY_CONFLICT_EXAMPLE}},
    }


IDEMPOTENCY_KEY_PARAMETER = {
    "name": "Idempotency-Key",
    "in": "header",
    "required": False,
    "description": (
        "副作用请求的幂等键：同一用户在同一动作作用域内，同键同内容返回原结果，"
        "同键不同内容返回 409 idempotency_conflict。作用域由服务端按端点固定。"
    ),
    "schema": {"type": "string", "maxLength": 128},
}
