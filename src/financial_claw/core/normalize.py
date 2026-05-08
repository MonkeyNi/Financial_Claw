from __future__ import annotations

import re


def parse_number(s: str) -> float | None:
    s = str(s).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    s = re.sub(r"[^\d.-]", "", s)
    if s in {"", "-", "."}:
        return None
    v = float(s)
    return -v if neg else v
