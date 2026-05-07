#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


DEFAULT_LEGACY_ROOT = "Financial_Statment"
DEFAULT_COMPANIES_ROOT = "companies"
FINANCIAL_STATEMENTS_DIRNAME = "Financial_Statements"
FINAL_EXCEL_DIRNAME = "final_excel"


@dataclass(frozen=True)
class PlannedOp:
    action: str
    src: Path | None = None
    dst: Path | None = None
    note: str | None = None

    def format(self) -> str:
        parts: list[str] = [self.action]
        if self.src is not None:
            parts.append(str(self.src))
        if self.dst is not None:
            parts.append("->")
            parts.append(str(self.dst))
        if self.note:
            parts.append(f"({self.note})")
        return " ".join(parts)


def is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def iter_company_dirs(legacy_root: Path) -> list[Path]:
    if not legacy_root.exists():
        return []
    if not legacy_root.is_dir():
        return []

    company_dirs: list[Path] = []
    for child in sorted(legacy_root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.lower() == "tmp":
            continue
        company_dirs.append(child)
    return company_dirs


def plan_ops(
    legacy_root: Path,
    companies_root: Path,
    mode: str,
) -> tuple[list[PlannedOp], dict[str, int]]:
    ops: list[PlannedOp] = []
    stats = {
        "companies_seen": 0,
        "pdfs_seen": 0,
        "pdfs_planned": 0,
        "skipped_exists": 0,
        "skipped_non_pdf": 0,
    }

    company_dirs = iter_company_dirs(legacy_root)
    for company_dir in company_dirs:
        stats["companies_seen"] += 1
        company_name = company_dir.name

        target_company_root = companies_root / company_name
        target_statements_dir = target_company_root / FINANCIAL_STATEMENTS_DIRNAME
        target_excel_dir = target_company_root / FINAL_EXCEL_DIRNAME

        # Always ensure target dirs exist.
        ops.append(PlannedOp("mkdir", dst=target_statements_dir))
        ops.append(PlannedOp("mkdir", dst=target_excel_dir))

        for item in sorted(company_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.is_dir():
                stats["skipped_non_pdf"] += 1
                continue
            if not is_pdf(item):
                stats["skipped_non_pdf"] += 1
                continue

            stats["pdfs_seen"] += 1
            dst = target_statements_dir / item.name
            if dst.exists():
                stats["skipped_exists"] += 1
                ops.append(
                    PlannedOp(
                        "skip",
                        src=item,
                        dst=dst,
                        note="destination exists",
                    )
                )
                continue

            stats["pdfs_planned"] += 1
            if mode == "move":
                ops.append(PlannedOp("move", src=item, dst=dst))
            else:
                ops.append(PlannedOp("copy", src=item, dst=dst))

    return ops, stats


def apply_ops(ops: list[PlannedOp], dry_run: bool) -> dict[str, int]:
    applied = {
        "mkdir": 0,
        "move": 0,
        "copy": 0,
        "skip": 0,
    }

    for op in ops:
        if op.action == "mkdir":
            applied["mkdir"] += 1
            if dry_run:
                continue
            assert op.dst is not None
            op.dst.mkdir(parents=True, exist_ok=True)
            continue

        if op.action in ("move", "copy"):
            applied[op.action] += 1
            if dry_run:
                continue
            assert op.src is not None and op.dst is not None
            op.dst.parent.mkdir(parents=True, exist_ok=True)
            if op.action == "move":
                shutil.move(str(op.src), str(op.dst))
            else:
                shutil.copy2(str(op.src), str(op.dst))
            continue

        if op.action == "skip":
            applied["skip"] += 1
            continue

        raise RuntimeError(f"Unknown op action: {op.action}")

    return applied


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="normalize_company_folders.py",
        description=(
            "Normalize folder structure to companies/<Company>/{Financial_Statements,final_excel}.\n"
            "Migrates PDFs from legacy Financial_Statment/<Company>/*.pdf.\n"
            "Does NOT touch Financial_Statment/tmp."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--legacy-root",
        default=DEFAULT_LEGACY_ROOT,
        help=f"Legacy root directory (default: {DEFAULT_LEGACY_ROOT})",
    )
    p.add_argument(
        "--companies-root",
        default=DEFAULT_COMPANIES_ROOT,
        help=f"Target companies directory (default: {DEFAULT_COMPANIES_ROOT})",
    )
    p.add_argument(
        "--mode",
        choices=["move", "copy"],
        default="move",
        help="Move or copy PDFs into canonical layout (default: move)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations only (recommended first run).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary.",
    )
    return p


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    legacy_root = (repo_root / args.legacy_root).resolve()
    companies_root = (repo_root / args.companies_root).resolve()

    if not legacy_root.exists():
        logger.error("legacy root not found: {}", legacy_root)
        return 2

    if not legacy_root.is_dir():
        logger.error("legacy root is not a directory: {}", legacy_root)
        return 2

    # Refuse to operate if companies_root is a file (directory ok even if missing).
    if companies_root.exists() and not companies_root.is_dir():
        logger.error("companies root is not a directory: {}", companies_root)
        return 2

    ops, stats = plan_ops(legacy_root=legacy_root, companies_root=companies_root, mode=args.mode)

    if not args.quiet:
        logger.info("repo_root: {}", repo_root)
        logger.info("legacy_root: {}", legacy_root)
        logger.info("companies_root: {}", companies_root)
        logger.info("mode: {}", args.mode)
        logger.info("dry_run: {}", bool(args.dry_run))
        logger.info("")
        for op in ops:
            logger.info(op.format())
        logger.info("")

    applied = apply_ops(ops, dry_run=bool(args.dry_run))

    logger.info("summary:")
    logger.info("  companies_seen: {}", stats["companies_seen"])
    logger.info("  pdfs_seen: {}", stats["pdfs_seen"])
    logger.info("  pdfs_planned: {}", stats["pdfs_planned"])
    logger.info("  skipped_exists: {}", stats["skipped_exists"])
    logger.info("  skipped_non_pdf: {}", stats["skipped_non_pdf"])
    logger.info("  mkdir_ops: {}", applied["mkdir"])
    logger.info("  move_ops: {}", applied["move"])
    logger.info("  copy_ops: {}", applied["copy"])
    logger.info("  skip_ops: {}", applied["skip"])

    if args.dry_run:
        logger.info("(dry-run) no filesystem changes were made.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

