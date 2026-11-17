"""ASGI entrypoint: uvicorn app.asgi:app (configuration comes from the environment)."""

from app.config import load_settings
from app.main import create_app

app = create_app(load_settings())
