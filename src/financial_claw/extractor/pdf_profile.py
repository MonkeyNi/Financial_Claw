from __future__ import annotations

from pathlib import Path

from .pymupdf_compat import fitz

from .models import PageProfile


def load_page_profiles(pdf_path: Path) -> list[PageProfile]:
    doc = fitz.open(pdf_path)
    profiles: list[PageProfile] = []
    for idx in range(doc.page_count):
        page = doc.load_page(idx)
        text = page.get_text("text") or ""
        words = page.get_text("words") or []
        rect = page.rect
        lines = [line for line in text.splitlines() if line.strip()]
        profiles.append(
            PageProfile(
                page_number=idx + 1,
                text=text,
                line_count=len(lines),
                word_count=len(words),
                has_embedded_text=len(words) >= 20,
                width=float(rect.width),
                height=float(rect.height),
            )
        )
    return profiles


def page_lines_from_words(page: fitz.Page, y_tolerance: float = 3.0) -> list[list[tuple]]:
    words = sorted(page.get_text("words") or [], key=lambda w: (round(w[1] / y_tolerance), w[0]))
    lines: list[list[tuple]] = []
    for word in words:
        if not lines:
            lines.append([word])
            continue
        prev_y = sum(w[1] for w in lines[-1]) / len(lines[-1])
        if abs(word[1] - prev_y) <= y_tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def extract_page_text_debug(pdf_path: Path, debug_dir: Path) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    for idx in range(doc.page_count):
        text = doc.load_page(idx).get_text("text") or ""
        (debug_dir / f"page_{idx + 1:04d}.txt").write_text(text, encoding="utf-8")
