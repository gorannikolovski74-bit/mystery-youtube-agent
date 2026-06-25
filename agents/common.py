"""Shared helpers for all agents: paths, env loading, logging, JSON state.

Keeping this tiny and dependency-light so every agent can import it without
pulling in heavy libraries it does not need.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

# --- Project paths -----------------------------------------------------------
# common.py lives in agents/, so the project root is one level up.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"
LOGS_DIR = ROOT / "logs"
ASSETS_DIR = ROOT / "assets"

TOPICS_DONE_FILE = CONFIG_DIR / "topics_done.json"
STYLE_PROFILE_FILE = CONFIG_DIR / "style_profile.md"
ENV_FILE = CONFIG_DIR / "apis.env"


def load_env() -> None:
    """Load config/apis.env into os.environ if present.

    Uses python-dotenv when available, otherwise falls back to a minimal
    parser so the agents can run in a bare environment.
    """
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(ENV_FILE)
        return
    except ImportError:
        pass

    # Minimal fallback parser: KEY=VALUE lines, ignores comments/blanks.
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comments and surrounding quotes.
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to logs/pipeline.log and the console."""
    LOGS_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(LOGS_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    return logger


def load_topics_done() -> list[dict]:
    """Return the list of already-used topics (empty list if none)."""
    if not TOPICS_DONE_FILE.exists():
        return []
    try:
        return json.loads(TOPICS_DONE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


def topic_already_used(topic_title: str) -> bool:
    """Case-insensitive check against the topics_done log."""
    needle = topic_title.strip().lower()
    return any(t.get("topic", "").strip().lower() == needle for t in load_topics_done())


def mark_topic_done(topic: dict) -> None:
    """Append a finished topic to topics_done.json."""
    done = load_topics_done()
    done.append(topic)
    TOPICS_DONE_FILE.write_text(
        json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def anthropic_client():
    """Build an Anthropic client from the env. Raises if the key is missing."""
    load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (see config/apis.env).")
    from anthropic import Anthropic  # imported lazily

    return Anthropic(api_key=api_key)


def anthropic_model() -> str:
    """The Claude model id to use for ranking and script writing."""
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
