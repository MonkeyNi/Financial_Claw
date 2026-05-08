from __future__ import annotations

import re
from pathlib import Path

from .models import PageProfile


def infer_company_from_path(pdf_path: Path) -> str:
    parts = pdf_path.parts
    if "companies" in parts:
        idx = parts.index("companies")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return pdf_path.stem


def extract_metadata(pdf_path: Path, profiles: list[PageProfile]) -> dict[str, str]:
    text = "\n".join(profile.text for profile in profiles[:12])
    all_text_sample = "\n".join(profile.text for profile in profiles[:40])
    period_match = re.search(r"(?:year|period|quarter|three months|six months|nine months)\s+ended\s+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", all_text_sample, re.I)
    as_at_match = re.search(r"as\s+at\s+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", all_text_sample, re.I)
    currency_match = re.search(r"expressed\s+in\s+([A-Za-z ]+ dollars)", all_text_sample, re.I)
    unit_match = re.search(r"\$ ?(M|000|million|thousand)", all_text_sample, re.I)
    report_type = "annual" if re.search(r"annual report", text, re.I) else "quarterly/interim_or_unknown"
    return {
        "source_pdf": str(pdf_path),
        "company": infer_company_from_path(pdf_path),
        "report_type": report_type,
        "period_end": period_match.group(1) if period_match else "",
        "as_at_date": as_at_match.group(1) if as_at_match else "",
        "currency": currency_match.group(1) if currency_match else "",
        "unit": unit_match.group(0) if unit_match else "",
        "page_count": str(len(profiles)),
        "embedded_text_pages": str(sum(1 for p in profiles if p.has_embedded_text)),
    }
