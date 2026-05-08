from __future__ import annotations

import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from loguru import logger


@dataclass(frozen=True)
class MinimaxConfig:
    api_key: str
    api_base: str = "https://api.minimax.io"
    model: str = "MiniMax-Text-01"
    timeout_s: int = 120


def _data_url_from_local_image(image_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime:
        mime = "image/png"
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def minimax_chatcompletion_v2_with_image(
    *,
    cfg: MinimaxConfig,
    prompt: str,
    image_path: Path | None = None,
    image_url: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    if bool(image_path) == bool(image_url):
        raise ValueError("Exactly one of image_path or image_url must be provided.")

    if image_path:
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))
        resolved_url = _data_url_from_local_image(image_path)
    else:
        resolved_url = str(image_url)

    url = f"{cfg.api_base.rstrip('/')}/v1/text/chatcompletion_v2"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {
                "role": "user",
                "name": "User",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": resolved_url}},
                ],
            }
        ],
        "temperature": temperature,
    }

    logger.debug("Calling MiniMax endpoint: {}", url)
    resp = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout_s)
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("MiniMax HTTP error: {} {}", resp.status_code, resp.text[:2000])
        raise
    return resp.json()


def _load_dotenv_if_present(dotenv_path: Path) -> None:
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
        logger.debug("Loaded dotenv: {}", str(dotenv_path))
    except Exception as e:
        logger.warning("Failed to load dotenv {}: {}", str(dotenv_path), e)


def load_config_from_env() -> MinimaxConfig:
    # Prefer local config file next to this module when present.
    _load_dotenv_if_present(Path(__file__).resolve().parent / ".env")

    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing env MINIMAX_API_KEY")

    api_base = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.io").strip()
    model = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01").strip()
    timeout_s = int(os.environ.get("MINIMAX_TIMEOUT_S", "120"))
    return MinimaxConfig(api_key=api_key, api_base=api_base, model=model, timeout_s=timeout_s)
