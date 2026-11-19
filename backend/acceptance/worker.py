from acceptance.adapters import install
install()
from app.modules.async_execution.celery_app import celery_app
