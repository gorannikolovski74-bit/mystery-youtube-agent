"""Alert Agent — Telegram notifications on success / failure.

No-ops gracefully (just logs) when Telegram credentials are not configured, so
it never becomes the reason the pipeline crashes.
"""
from __future__ import annotations

import os

import requests

from agents.common import get_logger, load_env

log = get_logger("alert")

HTTP_TIMEOUT = 15


def _send(message: str) -> None:
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram not configured — alert not sent: %s", message)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        log.warning("Failed to send Telegram message: %s", exc)


def success(title: str, youtube_url: str) -> None:
    _send(f"✅ Video uploaded!\n\U0001F4F9 {title}\n\U0001F517 {youtube_url}")


def error(step: str, error_message: str) -> None:
    _send(f"❌ Pipeline error at step '{step}':\n{error_message}")


def run(*args, **kwargs):
    raise NotImplementedError("Use alert_agent.success() / alert_agent.error().")
