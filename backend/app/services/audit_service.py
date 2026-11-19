"""Cross-module audit writing (task 2.7).

`record_operation` is the single entry point for operation_logs; `mask`
enforces the redaction convention so credentials (passwords, tokens,
model keys, ...) never reach the log detail payload.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

MASKED = "***"

MASK_KEY_PATTERNS = ("password", "token", "secret", "key", "credential", "authorization")


def mask(value: Any) -> Any:
    """Recursively mask sensitive fields in dicts/lists; other values pass through."""
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if any(pattern in k.lower() for pattern in MASK_KEY_PATTERNS):
                masked[k] = MASKED
            else:
                masked[k] = mask(v)
        return masked
    if isinstance(value, list):
        return [mask(item) for item in value]
    return value


def record_operation(
    conn: Connection,
    *,
    user_id: UUID | str | None,
    action: str,
    object_type: str,
    object_id: UUID | str | None = None,
    result: str = "success",
    detail: dict[str, Any] | None = None,
) -> str:
    """Write one audit row. Detail is masked before storage; the function
    itself never raises to the caller's business flow (audit failures are
    logged, not propagated)."""
    import json
    import logging

    safe_detail = mask(detail or {})
    try:
        row = conn.execute(
            text(
                "INSERT INTO operation_logs (user_id, action, object_type, object_id, "
                "result, detail) VALUES (:user_id, :action, :object_type, :object_id, "
                ":result, CAST(:detail AS jsonb)) RETURNING id"
            ),
            {
                "user_id": str(user_id) if user_id else None,
                "action": action[:64],
                "object_type": object_type[:64],
                "object_id": str(object_id) if object_id else None,
                "result": result,
                "detail": json.dumps(safe_detail, ensure_ascii=False, default=str),
            },
        ).scalar_one()
        return str(row)
    except Exception:  # noqa: BLE001 - audit must not break business flow
        logging.getLogger(__name__).exception("failed to write operation log")
        return ""
