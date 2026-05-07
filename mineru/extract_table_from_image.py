from __future__ import annotations

import argparse
import re
from pathlib import Path

from loguru import logger

try:
    # Package execution (python -m mineru.extract_table_from_image)
    from .mineru_api import (
        MinerUConfig,
        agent_extract_markdown_from_local_file,
        load_mineru_api_token,
        load_mineru_base_url,
        precision_extract_markdown_from_local_file,
    )
except ImportError:  # pragma: no cover
    # Direct script execution (python mineru/extract_table_from_image.py)
    from mineru_api import (  # type: ignore
        MinerUConfig,
        agent_extract_markdown_from_local_file,
        load_mineru_api_token,
        load_mineru_base_url,
        precision_extract_markdown_from_local_file,
    )


def _extract_tables_from_markdown(md: str) -> list[str]:
    """
    Best-effort extraction of HTML tables from MinerU markdown output.
    MinerU often emits tables as HTML (<table>...</table>) blocks.
    """
    if not md:
        return []
    return re.findall(r"(?is)<table\b.*?</table>", md)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract tables from an image using MinerU Open API.")
    ap.add_argument("--image", type=str, required=True, help="Local image path (png/jpg/webp).")
    ap.add_argument(
        "--mode",
        type=str,
        default="precision",
        choices=["agent", "precision"],
        help="precision: Token required; agent: no token (IP rate-limited).",
    )
    ap.add_argument(
        "--out-md",
        type=str,
        default="",
        help="Optional output markdown path. Defaults to <image_stem>.mineru.md in the same folder.",
    )
    ap.add_argument(
        "--out-tables-html",
        type=str,
        default="",
        help="Optional output HTML containing extracted <table> blocks.",
    )
    args = ap.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    out_md = (
        Path(args.out_md).expanduser().resolve()
        if args.out_md
        else image_path.with_suffix(".mineru.md")
    )
    out_tables_html = Path(args.out_tables_html).expanduser().resolve() if args.out_tables_html else None

    base_url = load_mineru_base_url()

    if args.mode == "precision":
        token = load_mineru_api_token(Path(__file__).resolve().parent)
        cfg = MinerUConfig(base_url=base_url, api_token=token, timeout_s=60.0)
        md = precision_extract_markdown_from_local_file(cfg, image_path)
    else:
        md = agent_extract_markdown_from_local_file(base_url, image_path)

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    logger.info("Wrote markdown to {}", out_md)

    tables = _extract_tables_from_markdown(md)
    logger.info("Detected {} HTML table block(s)", len(tables))

    if out_tables_html is not None:
        html = "<!doctype html><meta charset='utf-8'>\n" + "\n<hr/>\n".join(tables)
        out_tables_html.parent.mkdir(parents=True, exist_ok=True)
        out_tables_html.write_text(html, encoding="utf-8")
        logger.info("Wrote tables HTML to {}", out_tables_html)


if __name__ == "__main__":
    main()

