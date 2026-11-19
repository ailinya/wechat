FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /srv/backend
RUN pip install --no-cache-dir uv==0.10.12
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
ENV PATH="/srv/backend/.venv/bin:$PATH"
RUN groupadd --gid 10001 wetchat && useradd --uid 10001 --gid wetchat --create-home wetchat
USER wetchat
EXPOSE 8000
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS acceptance
COPY backend/acceptance ./acceptance
