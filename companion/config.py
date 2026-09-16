from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PACKAGE_ROOT = Path(__file__).resolve().parent
CORPUS_DIR = PACKAGE_ROOT / "corpus"
EVAL_DIR = PACKAGE_ROOT / "eval"
CACHE_DIR = PACKAGE_ROOT / ".cache"

TORQUE_NCR_QUERY = (
    "SN-4419 failed torque. What does current procedure require, and what should we hold?"
)
GARBAGE_QUERY = "How do I change the default printer on macOS Sequoia?"

CHIPS = {
    "torque_ncr": TORQUE_NCR_QUERY,
    "garbage": GARBAGE_QUERY,
}

DEFAULT_PLANT = "B"
DEFAULT_LOT = "L-8819"
DEMO_THREAD = "ncr-1042"
PLANT_DISPLAY = "Plant B"


def resolve_provider(explicit: str | None = None) -> str:
    """LLM provider: explicit arg, then COMPANION_PROVIDER, else gemini if keyed."""
    if explicit and explicit.strip():
        return explicit.strip().lower()
    env = (os.environ.get("COMPANION_PROVIDER") or "").strip()
    if env:
        return env.lower()
    return "gemini" if (os.environ.get("GOOGLE_API_KEY") or "").strip() else "local"


def demo_password() -> str:
    return (os.environ.get("DEMO_PASSWORD") or "").strip()


def auth_required() -> bool:
    return bool(demo_password())
