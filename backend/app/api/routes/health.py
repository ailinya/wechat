from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.api.deps import get_settings
from app.config import Settings
from app.services.readiness_service import check
from pydantic import BaseModel
from typing import Literal


class DependencyReady(BaseModel):
    ready: bool
    error_code: str | None
    latency_ms: float


class ReadinessOut(BaseModel):
    status: Literal['ready','degraded']
    checks: dict[str,DependencyReady]


router = APIRouter(tags=["health"])


@router.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get('/ready', response_model=ReadinessOut, responses={503:{'model':ReadinessOut,'description':'数据库、Broker、存储或迁移版本未就绪'}})
def readiness(settings: Settings = Depends(get_settings)):
    result = check(settings)
    return JSONResponse(result,status_code=200 if result['status']=='ready' else 503)
