from fastapi import APIRouter

from app.api.routes import async_jobs, auth, collection, files, materials, roles, users

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(async_jobs.router)
api_router.include_router(files.router)
api_router.include_router(collection.router)
api_router.include_router(materials.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
