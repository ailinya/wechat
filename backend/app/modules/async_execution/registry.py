"""Handler registry for async job types (task 2.3).

Handlers receive a JobContext and are responsible for calling
``context.checkpoint()`` between side effects so a cancelled job stops
without producing further business artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import Connection

Handler = Callable[["JobContext"], Any]


@dataclass
class JobContext:
    job_id: str
    job_type: str
    payload: dict
    conn: Connection

    def checkpoint(self) -> None:
        """Raise JobCancelled when the job is no longer running."""
        from app.services import async_job_service

        if not async_job_service.is_active(self.conn, self.job_id):
            raise JobCancelled()


class JobCancelled(Exception):
    """Raised at a checkpoint after the user cancelled the job."""


_REGISTRY: dict[str, Handler] = {}
_ENGINE_REGISTRY: dict[str, Callable] = {}


def register_engine_handler(job_type: str, handler: Callable) -> None:
    """Handlers with network I/O own their transactions using an engine."""
    _ENGINE_REGISTRY[job_type] = handler


def get_engine_handler(job_type: str):
    return _ENGINE_REGISTRY.get(job_type)


def register_handler(job_type: str, handler: Handler) -> None:
    _REGISTRY[job_type] = handler


def get_handler(job_type: str) -> Handler | None:
    return _REGISTRY.get(job_type)
