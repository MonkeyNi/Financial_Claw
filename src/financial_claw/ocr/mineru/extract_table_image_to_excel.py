from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from loguru import logger

try:
    # Package execution (python -m financial_claw.ocr.mineru.extract_table_image_to_excel)
    from .mineru_api import (
        MinerUConfig,
        agent_extract_markdown_from_local_file,
        load_mineru_api_token,
        load_mineru_base_url,
        precision_extract_markdown_from_local_file,
    )
except ImportError:  # pragma: no cover
    # Direct script execution from this directory.
    from mineru_api import (  # type: ignore
        MinerUConfig,
        agent_extract_markdown_from_local_file,
        load_mineru_api_token,
        load_mineru_base_url,
        precision_extract_markdown_from_local_file,
    )


def _load_md_to_excel_module() -> ModuleType:
    """
    Load md_table_to_excel from the same directory as this script.
    """
    src = Path(__file__).resolve().parent / "md_table_to_excel.py"
    if not src.exists():
        raise FileNotFoundError(f"Missing converter script: {src}")

    spec = importlib.util.spec_from_file_location("md_table_to_excel", src)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from: {src}")
    mod = importlib.util.module_from_spec(spec)
    # Register before exec_module so decorators (e.g. dataclasses) can resolve
    # sys.modules[__module__] during class processing.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mineru_markdown_from_image(image_path: Path, mode: str) -> str:
    base_url = load_mineru_base_url()
    if mode == "precision":
        token = load_mineru_api_token(Path(__file__).resolve().parent)
        cfg = MinerUConfig(base_url=base_url, api_token=token, timeout_s=60.0)
        return precision_extract_markdown_from_local_file(cfg, image_path)
    return agent_extract_markdown_from_local_file(base_url, image_path)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract tables from an image with MinerU, then write them to Excel (.xlsx)."
    )
    ap.add_argument("--image", type=str, required=True, help="Local image path (png/jpg/webp).")
    ap.add_argument(
        "--mode",
        type=str,
        default="precision",
        choices=["agent", "precision"],
        help="precision: Token required; agent: no token (IP rate-limited).",
    )
    ap.add_argument(
        "--out-xlsx",
        type=str,
        default="",
        help="Output xlsx path. Defaults to <image_stem>.xlsx in the same folder.",
    )
    ap.add_argument(
        "--save-md",
        type=str,
        default="",
        help="Optional path to also save MinerU markdown output.",
    )
    args = ap.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    out_xlsx = (
        Path(args.out_xlsx).expanduser().resolve()
        if args.out_xlsx
        else image_path.with_suffix(".xlsx")
    )
    save_md = Path(args.save_md).expanduser().resolve() if args.save_md else None

    md = _mineru_markdown_from_image(image_path, args.mode)

    if save_md is not None:
        save_md.parent.mkdir(parents=True, exist_ok=True)
        save_md.write_text(md, encoding="utf-8")
        logger.info("Wrote markdown to {}", save_md)

    conv = _load_md_to_excel_module()

    tables = conv._extract_tables(md)  # type: ignore[attr-defined]
    if not tables:
        raise RuntimeError("No <table> found in MinerU markdown output.")

    grids = [conv._table_cells_to_grid(t) for t in tables]  # type: ignore[attr-defined]
    logger.info("Found {} table(s). Writing xlsx: {}", len(grids), out_xlsx)
    conv._write_xlsx(grids, out_xlsx)  # type: ignore[attr-defined]
    logger.info("Done.")


if __name__ == "__main__":
    main()
