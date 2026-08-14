"""Environment loading and required-key verification.

Loads .env once via python-dotenv. Never logs or prints key values.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

REQUIRED_KEYS = [
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "GITHUB_TOKEN",
]


def check_required_keys(keys: list[str] | None = None) -> dict[str, bool]:
    """Return {key_name: present_bool} without ever reading/printing values."""
    keys = keys or REQUIRED_KEYS
    return {k: bool(os.environ.get(k)) for k in keys}


def require_key(name: str) -> str:
    """Fetch a single required env var value for internal backend use only.

    Callers must never log, print, or return this value to the frontend.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_optional_key(name: str) -> str | None:
    return os.environ.get(name)
