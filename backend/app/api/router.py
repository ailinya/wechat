from fastapi import APIRouter

from app.api.routes import (
    async_jobs,
    auth,
    collection,
    files,
    materials,
    model_configs,
    roles,
    search_configs,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(async_jobs.router)
api_router.include_router(files.router)
api_router.include_router(collection.router)
api_router.include_router(materials.router)
api_router.include_router(search_configs.router)
api_router.include_router(model_configs.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
