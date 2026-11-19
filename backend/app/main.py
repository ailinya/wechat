from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.config import Settings, load_settings
from app.errors import install_error_handlers
from app.logging_config import configure_logging
import logging
import time
from uuid import uuid4


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    configure_logging(app_settings.log_level)

    application = FastAPI(title=app_settings.app_name, version="0.1.0")
    application.state.settings = app_settings
    @application.middleware('http')
    async def observe_request(request, call_next):
        started = time.monotonic()
        request_id = str(uuid4())
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Request-ID'] = request_id
            response.headers['Server-Timing'] = f'app;dur={(time.monotonic()-started)*1000:.2f}'
            return response
        finally:
            route = request.scope.get('route')
            logging.getLogger('app.request').info('request.completed', extra={'request_id':request_id,'method':request.method,'path':getattr(route,'path','unmatched'),'status':status,'duration_ms':round((time.monotonic()-started)*1000,2)})
    application.include_router(health_router)
    from app.api.responses import error_responses
    application.include_router(api_router, prefix="/api/v1", responses=error_responses(400,401,403,404,409,422,503))
    install_error_handlers(application)
    return application
