from fastapi import APIRouter

from app.api.routes import (
    async_jobs,
    articles,
    auth,
    collection,
    creation,
    files,
    materials,
    model_configs,
    roles,
    search_configs,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(articles.router)
api_router.include_router(articles.review_router)
api_router.include_router(async_jobs.router)
api_router.include_router(files.router)
api_router.include_router(collection.router)
api_router.include_router(creation.rules)
api_router.include_router(creation.tasks)
api_router.include_router(materials.router)
api_router.include_router(search_configs.router)
api_router.include_router(model_configs.router)
api_router.include_router(users.router)

from app.api.routes import wechat_accounts, publishing, wechat_drafts
api_router.include_router(wechat_accounts.router)
api_router.include_router(publishing.router)
api_router.include_router(wechat_drafts.router)
api_router.include_router(roles.router)
from app.api.routes import operations
api_router.include_router(operations.router)
from app.api.routes import assistance
api_router.include_router(assistance.router)
