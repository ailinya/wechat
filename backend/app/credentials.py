"""Resolve only the requested secret without loading test/runtime URLs globally."""

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def resolve_credential(reference: str | None) -> str | None:
    if not reference:
        return None
    if reference in os.environ:
        return os.environ[reference]
    return dotenv_values(ENV_FILE, encoding="utf-8-sig").get(reference)
