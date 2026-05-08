from __future__ import annotations

from pathlib import Path

from .pymupdf_compat import fitz


def render_pdf_page_to_png(pdf_path: Path, page_number: int, output_dir: Path, dpi: int = 220) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"page_{page_number:04d}_{dpi}dpi.png"
    if image_path.exists():
        return image_path

    doc = fitz.open(pdf_path)
    page = doc.load_page(page_number - 1)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pix.save(image_path)
    return image_path
