"""Creation rules and revision-bound manual creation requests."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query
from pydantic import ValidationError
from sqlalchemy import text

from app.api.deps import CurrentUserDep, DbSession, require_permission, verify_csrf
from app.schemas.auth import PermissionCode
from app.schemas.common import PaginatedResponse
from app.schemas.creation import CreationAccepted, CreationOutputOut, CreationTaskIn, CreationTaskOut, GenerationModelOut, RuleIn, RuleOut
from app.services import audit_service, creation_service
from app.errors import ApiError

rules = APIRouter(prefix="/creation-rules", tags=["creation"])
tasks = APIRouter(prefix="/creation-tasks", tags=["creation"])
READ = Depends(require_permission(PermissionCode.CREATION_READ))
WRITE = Depends(require_permission(PermissionCode.CREATION_WRITE))
CSRF = Depends(verify_csrf)


@rules.get("", response_model=PaginatedResponse[RuleOut])
def list_rules(db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _perm=READ):
    return creation_service.list_rules(db.connection(), page, page_size)


@rules.post("", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleIn, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    result = creation_service.save_rule(db.connection(), payload, user.id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_rule.create", object_type="creation_rule", object_id=result["id"])
    db.commit()
    return result


@rules.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: UUID, db: DbSession, _perm=READ):
    return creation_service.get_rule(db.connection(), rule_id)


@rules.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: UUID, payload: RuleIn, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    result = creation_service.save_rule(db.connection(), payload, user.id, rule_id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_rule.update", object_type="creation_rule", object_id=rule_id)
    db.commit()
    return result


@rules.patch("/{rule_id}", response_model=RuleOut)
def patch_rule(rule_id: UUID, db: DbSession, user: CurrentUserDep, changes: dict = Body(...), _csrf=CSRF, _perm=WRITE):
    existing = creation_service.get_rule(db.connection(), rule_id)
    permitted = set(RuleIn.model_fields)
    if set(changes) - permitted:
        raise ApiError(422, "invalid_rule", "存在未知规则字段")
    try:
        payload = RuleIn.model_validate({**{key: existing[key] for key in permitted}, **changes})
    except ValidationError:
        raise ApiError(422, "invalid_rule", "规则字段或条件无效") from None
    result = creation_service.save_rule(db.connection(), payload, user.id, rule_id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_rule.update", object_type="creation_rule", object_id=rule_id)
    db.commit()
    return result


@rules.delete("/{rule_id}", response_model=RuleOut)
def disable_rule(rule_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    creation_service.get_rule(db.connection(), rule_id)
    db.connection().execute(text("UPDATE creation_rules SET enabled=false,updated_at=now() WHERE id=:id"), {"id": str(rule_id)})
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_rule.disable", object_type="creation_rule", object_id=rule_id)
    result = creation_service.get_rule(db.connection(), rule_id)
    db.commit()
    return result


@rules.post("/{rule_id}/run", response_model=CreationAccepted, status_code=202)
def run_rule(rule_id: UUID, db: DbSession, user: CurrentUserDep, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128), _csrf=CSRF, _perm=WRITE):
    from uuid import uuid4

    result = creation_service.run_rule(db.connection(), rule_id, "manual", idempotency_key or str(uuid4()), trigger_source=str(user.id), user_id=user.id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_rule.run", object_type="creation_task", object_id=result["resource_id"])
    db.commit()
    return result


@tasks.get("", response_model=PaginatedResponse[CreationTaskOut])
def list_tasks(db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _perm=READ):
    return creation_service.list_tasks(db.connection(), page, page_size)


@tasks.post("", response_model=CreationAccepted, status_code=202)
def create_task(payload: CreationTaskIn, db: DbSession, user: CurrentUserDep, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128), _csrf=CSRF, _perm=WRITE):
    result = creation_service.create_manual(db.connection(), payload, user.id, idempotency_key)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_task.create", object_type="creation_task", object_id=result["resource_id"])
    db.commit()
    return result


@tasks.get("/models", response_model=list[GenerationModelOut])
def generation_models(db: DbSession, _perm=WRITE):
    from app.credentials import resolve_setting
    model_name = resolve_setting("MODEL_NAME")
    rows = db.connection().execute(text("SELECT id,name,model_name FROM model_configs WHERE purpose='generation' AND enabled ORDER BY name,id")).mappings().all()
    return [{**dict(row), "model_name": model_name or row["model_name"]} for row in rows]


@tasks.get('/target-accounts', response_model=list[dict[str, str]])
def target_accounts(db: DbSession, _perm=WRITE):
    return [dict(row) for row in db.connection().execute(text("SELECT id::text,name FROM wechat_accounts WHERE status='active' AND capabilities->'drafts'->>'available'='true' ORDER BY name,id")).mappings()]


@tasks.get("/{task_id}", response_model=CreationTaskOut)
def get_task(task_id: UUID, db: DbSession, _perm=READ):
    return creation_service.get_task(db.connection(), task_id)


@tasks.get("/{task_id}/outputs", response_model=list[CreationOutputOut])
def list_outputs(task_id: UUID, db: DbSession, _perm=READ):
    creation_service.get_task(db.connection(), task_id)
    return [dict(row) for row in db.connection().execute(text("SELECT * FROM creation_outputs WHERE creation_task_id=:id ORDER BY slot"), {"id": str(task_id)}).mappings().all()]


@tasks.post("/{task_id}/cancel", response_model=CreationTaskOut)
def cancel_task(task_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    result = creation_service.cancel_task(db.connection(), task_id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_task.cancel", object_type="creation_task", object_id=task_id)
    db.commit()
    return result


@tasks.post("/{task_id}/retry", response_model=CreationAccepted, status_code=202)
def retry_task(task_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    result = creation_service.retry_task(db.connection(), task_id, user.id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_task.retry", object_type="creation_task", object_id=task_id)
    db.commit()
    return result


@tasks.post("/{task_id}/regenerate", response_model=CreationAccepted, status_code=202)
def regenerate_task(task_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE):
    result = creation_service.regenerate_task(db.connection(), task_id, user.id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="creation_task.regenerate", object_type="creation_task", object_id=result["resource_id"])
    db.commit()
    return result
