from __future__ import annotations

import io
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
from loguru import logger


@dataclass(frozen=True)
class MinerUConfig:
    base_url: str
    api_token: str
    timeout_s: float = 60.0


def load_mineru_api_token(start_dir: Path) -> str:
    """
    Best-effort: read MINERU_API_TOKEN from env, else from a local .env file.
    """
    token = (os.getenv("MINERU_API_TOKEN") or "").strip()
    if token:
        return token

    env_path = start_dir / ".env"
    if not env_path.exists() or not env_path.is_file():
        return ""

    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "MINERU_API_TOKEN":
            return v.strip().strip("'").strip('"')
    return ""


def load_mineru_base_url() -> str:
    return (os.getenv("MINERU_BASE_URL") or "https://mineru.net").rstrip("/")


def _raise_for_api_error(resp_json: dict, context: str) -> None:
    code = resp_json.get("code")
    if code == 0:
        return
    msg = resp_json.get("msg")
    trace_id = resp_json.get("trace_id")
    raise RuntimeError(f"{context} failed: code={code} msg={msg!r} trace_id={trace_id!r}")


def _download_text(url: str, timeout_s: float) -> str:
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def _download_bytes(url: str, timeout_s: float) -> bytes:
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def precision_extract_markdown_from_local_file(
    cfg: MinerUConfig,
    file_path: Path,
    *,
    model_version: str = "vlm",
    enable_table: bool = True,
    enable_formula: bool = True,
    is_ocr: bool = False,
    language: str = "ch",
    poll_interval_s: float = 2.0,
    poll_timeout_s: float = 600.0,
) -> str:
    """
    Precision API does not support direct file upload on /api/v4/extract/task.
    For local files, use:
      1) POST /api/v4/file-urls/batch  (get signed PUT url(s))
      2) PUT upload to returned url
      3) GET  /api/v4/extract-results/batch/{batch_id} (poll until done)
      4) download full_zip_url and read full.md
    """
    if not cfg.api_token:
        raise RuntimeError("MINERU_API_TOKEN is required for precision mode.")

    file_path = file_path.expanduser().resolve()
    file_name = file_path.name

    headers = {
        "Authorization": f"Bearer {cfg.api_token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    apply_url = f"{cfg.base_url}/api/v4/file-urls/batch"
    payload: dict[str, Any] = {
        "files": [{"name": file_name}],
        "model_version": model_version,
        "enable_table": bool(enable_table),
        "enable_formula": bool(enable_formula),
        "is_ocr": bool(is_ocr),
        "language": language,
    }

    logger.info("Precision: requesting upload URL for {}", file_name)
    with httpx.Client(timeout=cfg.timeout_s, follow_redirects=True) as client:
        r = client.post(apply_url, headers=headers, json=payload)
        r.raise_for_status()
        resp_json = r.json()
    _raise_for_api_error(resp_json, "apply upload url")

    data = resp_json.get("data") or {}
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls") or []
    if not batch_id or not file_urls:
        raise RuntimeError(f"Unexpected response (missing batch_id/file_urls): {resp_json}")

    upload_url = file_urls[0]
    logger.info("Precision: uploading {} (PUT) ...", file_name)
    with httpx.Client(timeout=max(cfg.timeout_s, 300.0), follow_redirects=True) as client:
        with file_path.open("rb") as f:
            put = client.put(upload_url, content=f.read())
        put.raise_for_status()

    poll_url = f"{cfg.base_url}/api/v4/extract-results/batch/{batch_id}"
    start = time.time()
    while True:
        if time.time() - start > poll_timeout_s:
            raise TimeoutError(f"Precision polling timed out after {poll_timeout_s}s (batch_id={batch_id})")

        with httpx.Client(timeout=cfg.timeout_s, follow_redirects=True) as client:
            rr = client.get(poll_url, headers=headers)
            rr.raise_for_status()
            poll_json = rr.json()
        _raise_for_api_error(poll_json, "poll batch result")

        pdata = poll_json.get("data") or {}
        results = pdata.get("extract_result") or []

        # find by file_name (preferred) else first result
        hit: Optional[dict[str, Any]] = None
        for item in results:
            if (item or {}).get("file_name") == file_name:
                hit = item
                break
        if hit is None and results:
            hit = results[0]

        state = (hit or {}).get("state")
        if state in ("pending", "running", "waiting-file", "uploading", "converting"):
            logger.info("Precision: state={} ...", state)
            time.sleep(poll_interval_s)
            continue

        if state == "failed":
            err = (hit or {}).get("err_msg") or "unknown error"
            raise RuntimeError(f"Precision parse failed: {err}")

        if state == "done":
            zip_url = (hit or {}).get("full_zip_url")
            if not zip_url:
                raise RuntimeError(f"Precision done but missing full_zip_url: {poll_json}")
            logger.info("Precision: downloading result zip ...")
            zbytes = _download_bytes(zip_url, timeout_s=max(cfg.timeout_s, 300.0))
            # read directly from bytes
            with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                # prefer top-level full.md, else any */full.md
                names = zf.namelist()
                target = None
                if "full.md" in names:
                    target = "full.md"
                else:
                    for n in names:
                        if n.endswith("/full.md") or n.endswith("\\full.md"):
                            target = n
                            break
                if not target:
                    raise RuntimeError(f"Zip missing full.md. Entries: {names[:30]}")
                return zf.read(target).decode("utf-8", errors="replace")

        raise RuntimeError(f"Unknown precision state: {state!r} ({hit})")


def agent_extract_markdown_from_local_file(
    base_url: str,
    file_path: Path,
    *,
    enable_table: bool = True,
    enable_formula: bool = True,
    is_ocr: bool = False,
    language: str = "ch",
    page_range: str = "",
    timeout_s: float = 60.0,
    poll_interval_s: float = 2.0,
    poll_timeout_s: float = 300.0,
) -> str:
    """
    Agent lightweight API signed upload flow:
      1) POST /api/v1/agent/parse/file   -> task_id, file_url
      2) PUT file_url
      3) GET /api/v1/agent/parse/{task_id} until done -> markdown_url
      4) download markdown_url
    """
    file_path = file_path.expanduser().resolve()
    file_name = file_path.name

    submit_url = f"{base_url}/api/v1/agent/parse/file"
    payload: dict[str, Any] = {
        "file_name": file_name,
        "language": language,
        "enable_table": bool(enable_table),
        "is_ocr": bool(is_ocr),
        "enable_formula": bool(enable_formula),
    }
    if page_range.strip():
        payload["page_range"] = page_range.strip()

    logger.info("Agent: requesting signed upload URL for {}", file_name)
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        r = client.post(submit_url, json=payload)
        r.raise_for_status()
        resp_json = r.json()
    _raise_for_api_error(resp_json, "agent submit file")

    data = resp_json.get("data") or {}
    task_id = data.get("task_id")
    file_url = data.get("file_url")
    if not task_id or not file_url:
        raise RuntimeError(f"Unexpected agent submit response: {resp_json}")

    logger.info("Agent: uploading {} (PUT) ...", file_name)
    with httpx.Client(timeout=max(timeout_s, 300.0), follow_redirects=True) as client:
        with file_path.open("rb") as f:
            put = client.put(file_url, content=f.read())
        put.raise_for_status()

    poll_url = f"{base_url}/api/v1/agent/parse/{task_id}"
    start = time.time()
    while True:
        if time.time() - start > poll_timeout_s:
            raise TimeoutError(f"Agent polling timed out after {poll_timeout_s}s (task_id={task_id})")

        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            rr = client.get(poll_url)
            rr.raise_for_status()
            poll_json = rr.json()
        _raise_for_api_error(poll_json, "agent poll")

        pdata = poll_json.get("data") or {}
        state = pdata.get("state")
        if state in ("waiting-file", "uploading", "pending", "running"):
            logger.info("Agent: state={} ...", state)
            time.sleep(poll_interval_s)
            continue
        if state == "failed":
            err = pdata.get("err_msg") or "unknown error"
            raise RuntimeError(f"Agent parse failed: {err}")
        if state == "done":
            md_url = pdata.get("markdown_url")
            if not md_url:
                raise RuntimeError(f"Agent done but missing markdown_url: {poll_json}")
            logger.info("Agent: downloading markdown ...")
            return _download_text(md_url, timeout_s=max(timeout_s, 300.0))

        raise RuntimeError(f"Unknown agent state: {state!r}")
