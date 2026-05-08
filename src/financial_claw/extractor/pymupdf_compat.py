from __future__ import annotations

from typing import Any


def _import_pymupdf() -> Any:
    # PyMuPDF supports both `import fitz` (legacy) and `import pymupdf` (newer).
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except Exception as e1:  # noqa: BLE001
        try:
            import fitz  # type: ignore

            return fitz
        except Exception as e2:  # noqa: BLE001
            raise ImportError(
                "PyMuPDF is required. Install it with `pip install pymupdf` "
                "and ensure the unrelated PyPI package `fitz` is not shadowing imports."
            ) from (e2 if e2 is not None else e1)


fitz = _import_pymupdf()

