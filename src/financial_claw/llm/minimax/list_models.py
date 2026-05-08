from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from financial_claw.llm.minimax.minimax_api import load_config_from_env


def _get_json(url: str, *, api_key: str, timeout_s: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=timeout_s)
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("MiniMax HTTP error: {} {}", resp.status_code, resp.text[:2000])
        raise
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type: {type(data)}")
    return data


def _summarize_openai_models(payload: dict[str, Any]) -> list[str]:
    # Expected: {"object":"list","data":[{"id": "...", ...}, ...]}
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for m in data:
        if isinstance(m, dict) and isinstance(m.get("id"), str):
            ids.append(m["id"])
    return ids


def _summarize_anthropic_models(payload: dict[str, Any]) -> list[str]:
    # Expected: {"data":[{"id": "...", ...}], "has_more":..., "first_id":..., "last_id":...}
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for m in data:
        if isinstance(m, dict) and isinstance(m.get("id"), str):
            ids.append(m["id"])
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description="List available MiniMax models for this API key.")
    ap.add_argument(
        "--api",
        choices=["openai", "anthropic"],
        default="openai",
        help="Which compatible API to use for listing models.",
    )
    ap.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional: save raw JSON response to this path.",
    )
    args = ap.parse_args()

    cfg = load_config_from_env()
    base = cfg.api_base.rstrip("/")

    if args.api == "openai":
        url = f"{base}/v1/models"
        payload = _get_json(url, api_key=cfg.api_key, timeout_s=cfg.timeout_s)
        model_ids = _summarize_openai_models(payload)
    else:
        url = f"{base}/anthropic/v1/models"
        payload = _get_json(url, api_key=cfg.api_key, timeout_s=cfg.timeout_s)
        model_ids = _summarize_anthropic_models(payload)

    logger.info("Endpoint: {}", url)
    logger.info("Found {} models", len(model_ids))
    for mid in model_ids:
        logger.info("model: {}", mid)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved raw response: {}", str(out_path))


if __name__ == "__main__":
    main()
