"""Thin OpenAI-compatible client wrapper (wired in subsequent milestones)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientSettings:
    base_url: str
    api_key: str | None
    chat_model: str
    vision_model: str


def load_client_settings(env: dict[str, str]) -> ClientSettings:
    return ClientSettings(
        base_url=env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=env.get("OPENAI_API_KEY"),
        chat_model=env.get("OPENAI_MODEL", "gpt-4.1-mini"),
        vision_model=env.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
    )
