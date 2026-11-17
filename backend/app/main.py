from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.config import Settings, load_settings
from app.errors import install_error_handlers
from app.logging_config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    configure_logging(app_settings.log_level)

    application = FastAPI(title=app_settings.app_name, version="0.1.0")
    application.state.settings = app_settings
    application.include_router(health_router)
    application.include_router(api_router, prefix="/api/v1")
    install_error_handlers(application)
    return application


app = create_app()
