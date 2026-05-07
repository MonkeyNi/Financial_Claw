from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from loguru import logger

try:
    from fa.models import ReportFile
except ModuleNotFoundError:  # allows `python fa/ingest.py ...` from repo root
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from fa.models import ReportFile  # type: ignore[no-redef]


def select_input_files(
    files: Iterable[tuple[str, str]],
    manifest: dict,
    explicit_files: list[str] | None,
) -> list[tuple[str, str]]:
    """Choose which (path, sha256) pairs to process.

    - If ``explicit_files`` is non-empty, return only entries whose path is in
      that list (order preserved from ``files``).
    - Otherwise return entries whose hash is not listed in
      ``manifest["seen_hashes"]``.
    """
    rows = list(files)
    if explicit_files:
        allow = set(explicit_files)
        return [f for f in rows if f[0] in allow]
    seen = set(manifest.get("seen_hashes", []))
    return [f for f in rows if f[1] not in seen]


def companies_root(default: str | Path = "companies") -> Path:
    return Path(default)


def company_dir(company: str, *, root: str | Path = "companies") -> Path:
    return companies_root(root) / company


def financial_statements_dir(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / "Financial_Statements"


def final_excel_dir(company: str, *, root: str | Path = "companies") -> Path:
    return company_dir(company, root=root) / "final_excel"


def manifest_path(company: str, *, root: str | Path = "companies") -> Path:
    return final_excel_dir(company, root=root) / ".processed.json"


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def discover_company_pdfs(
    company: str,
    *,
    root: str | Path = "companies",
) -> list[ReportFile]:
    """Find all PDFs under companies/<Company>/Financial_Statements.

    This function only discovers file metadata (path/hash/mtime); it does not
    parse or extract content.
    """
    fs_dir = financial_statements_dir(company, root=root)
    if not fs_dir.exists():
        return []

    pdf_paths = sorted(
        (p for p in fs_dir.glob("*.pdf") if p.is_file()),
        key=lambda p: p.name.lower(),
    )
    out: list[ReportFile] = []
    for p in pdf_paths:
        st = p.stat()
        out.append(
            ReportFile(
                company=company,
                pdf_path=str(p),
                file_name=p.name,
                sha256=_sha256_file(p),
                mtime=st.st_mtime,
            )
        )
    return out


def load_manifest(company: str, *, root: str | Path = "companies") -> dict:
    """Load incremental manifest from final_excel/.processed.json.

    Returns a dict containing at least:
      - seen_hashes: list[str]
    """
    mp = manifest_path(company, root=root)
    if not mp.exists():
        return {"seen_hashes": []}
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {"seen_hashes": []}
    if not isinstance(data, dict):
        return {"seen_hashes": []}
    seen = data.get("seen_hashes", [])
    if not isinstance(seen, list):
        seen = []
    data["seen_hashes"] = [str(x) for x in seen]
    return data


def save_manifest(company: str, manifest: dict, *, root: str | Path = "companies") -> None:
    """Persist manifest to final_excel/.processed.json.

    Note: pipeline steps later should update the manifest; ingest only provides
    the IO layer.
    """
    mp = manifest_path(company, root=root)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def final_excel_is_empty(company: str, *, root: str | Path = "companies") -> bool:
    d = final_excel_dir(company, root=root)
    if not d.exists():
        return True
    # "Empty" means no Excel outputs yet. Keep it simple: any .xlsx means not empty.
    return not any(d.glob("*.xlsx"))


@dataclass(frozen=True)
class IngestPlan:
    mode: Literal["init", "update"]
    company: str
    companies_root: str
    financial_statements_dir: str
    final_excel_dir: str
    manifest_path: str
    inputs: list[ReportFile]


def plan_init(company: str, *, root: str | Path = "companies") -> IngestPlan:
    reports = discover_company_pdfs(company, root=root)
    return IngestPlan(
        mode="init",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        manifest_path=str(manifest_path(company, root=root)),
        inputs=reports,
    )


def plan_update(
    company: str,
    *,
    root: str | Path = "companies",
    explicit_files: list[str] | None = None,
) -> IngestPlan:
    """Plan an incremental update for a company.

    Rules:
    - If companies/<Company>/final_excel is empty => behave like init (process all PDFs).
    - Otherwise select PDFs under Financial_Statements whose sha256 is not yet in manifest.
    - If explicit_files is provided, select only those PDFs (order preserved from discovery).
    """
    if final_excel_is_empty(company, root=root):
        return plan_init(company, root=root)

    manifest = load_manifest(company, root=root)
    reports = discover_company_pdfs(company, root=root)
    pairs = [(r.pdf_path, r.sha256) for r in reports]
    selected_pairs = select_input_files(pairs, manifest, explicit_files=explicit_files)
    allow_paths = {p for (p, _) in selected_pairs}
    selected_reports = [r for r in reports if r.pdf_path in allow_paths]

    return IngestPlan(
        mode="update",
        company=company,
        companies_root=str(companies_root(root)),
        financial_statements_dir=str(financial_statements_dir(company, root=root)),
        final_excel_dir=str(final_excel_dir(company, root=root)),
        manifest_path=str(manifest_path(company, root=root)),
        inputs=selected_reports,
    )


if __name__ == "__main__":
    import sys

    cwd_root = Path.cwd() / "companies"
    company = sys.argv[1] if len(sys.argv) > 1 else "GOODMAN"
    mode = sys.argv[2].lower() if len(sys.argv) > 2 else "update"

    if mode not in {"init", "update"}:
        raise SystemExit("usage: python fa/ingest.py [COMPANY] [init|update]")

    plan = plan_init(company, root=cwd_root) if mode == "init" else plan_update(company, root=cwd_root)
    logger.info("mode={} company={}", plan.mode, plan.company)
    logger.info("financial_statements_dir={}", plan.financial_statements_dir)
    logger.info("final_excel_dir={}", plan.final_excel_dir)
    logger.info("manifest_path={}", plan.manifest_path)
    logger.info("inputs={}", len(plan.inputs))
    for r in plan.inputs[:20]:
        logger.info("- {} sha256={}... mtime={}", r.file_name, r.sha256[:12], r.mtime)
