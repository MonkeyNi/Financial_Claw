from __future__ import annotations


# Applied to every string cell before numeric conversion and Excel writing.
CELL_TEXT_REPLACEMENTS: dict[str, str] = {
    "¥": "",
    "￦": "",
    "₩": "",
}
