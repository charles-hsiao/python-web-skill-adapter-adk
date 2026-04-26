from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class Settings:
    domain: str | None
    model: str
    timeout: float


def load_settings() -> Settings:
    timeout = DEFAULT_TIMEOUT
    raw_timeout = os.getenv("WEB_SKILL_TIMEOUT")
    if raw_timeout:
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = DEFAULT_TIMEOUT

    return Settings(
        domain=os.getenv("WEB_SKILL_DOMAIN"),
        model=os.getenv("WEB_SKILL_MODEL", DEFAULT_MODEL),
        timeout=timeout,
    )
