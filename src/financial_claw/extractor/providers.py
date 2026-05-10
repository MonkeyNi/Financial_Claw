from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import time
from time import perf_counter
import zipfile

from loguru import logger

from .page_renderer import render_pdf_page_to_png


class CloudOCRProvider:
    """Placeholder for Azure/Google/AWS/OpenAI OCR providers."""

    def extract_page(self, pdf_path: str, page_number: int) -> dict:
        raise NotImplementedError("Cloud OCR provider is a placeholder in this CLI prototype.")


class LLMFallbackProvider:
    """Placeholder for page classification and table repair fallback."""

    def classify_statement_pages(self, page_payloads: list[dict]) -> list[dict]:
        raise NotImplementedError("LLM fallback provider is a placeholder in this CLI prototype.")


@dataclass
class OCRTableResult:
    rows: list[list[str]]
    image_path: Path
    markdown_path: Path
    provider: str
    mode: str
    warnings: list[str]


class ConfigurationError(RuntimeError):
    pass


class MinerUOCRProvider:
    def __init__(
        self,
        debug_dir: Path,
        *,
        mode: str = "precision",
        language: str = "en",
        dpi: int = 220,
    ) -> None:
        if mode not in {"precision", "agent"}:
            raise ValueError(f"Unsupported MinerU mode: {mode}")
        self.debug_dir = debug_dir
        self.mode = mode
        self.language = language
        self.dpi = dpi

    def extract_page_table(self, pdf_path: Path, page_number: int) -> OCRTableResult:
        return self.extract_pages_tables(pdf_path, [page_number])[page_number]

    def extract_pages_tables(self, pdf_path: Path, page_numbers: list[int]) -> dict[int, OCRTableResult]:
        start = perf_counter()
        unique_page_numbers = sorted(set(page_numbers))
        logger.info("MinerU OCR requested for {} page(s)", len(unique_page_numbers))
        logger.debug("MinerU OCR pages: {}", unique_page_numbers)
        image_dir = self.debug_dir / "rendered_pages"
        md_dir = self.debug_dir / "mineru_markdown"
        md_dir.mkdir(parents=True, exist_ok=True)

        page_assets: dict[int, tuple[Path, Path]] = {}
        missing: dict[int, Path] = {}
        markdown_by_page: dict[int, str] = {}
        for page_number in unique_page_numbers:
            page_start = perf_counter()
            image_path = render_pdf_page_to_png(pdf_path, page_number, image_dir, dpi=self.dpi)
            markdown_path = md_dir / f"page_{page_number:04d}.mineru.md"
            page_assets[page_number] = (image_path, markdown_path)
            if markdown_path.exists():
                markdown_by_page[page_number] = markdown_path.read_text(encoding="utf-8", errors="replace")
                logger.debug(
                    "MinerU cache hit: page={} markdown={} elapsed={:.2f}s",
                    page_number,
                    markdown_path,
                    perf_counter() - page_start,
                )
            else:
                missing[page_number] = image_path
                logger.debug(
                    "Rendered page for MinerU: page={} image={} elapsed={:.2f}s",
                    page_number,
                    image_path,
                    perf_counter() - page_start,
                )

        if missing:
            logger.info("Submitting {} rendered page image(s) to MinerU mode={}", len(missing), self.mode)
            if self.mode == "precision":
                markdown_by_image = self._extract_markdowns_batch(list(missing.values()))
            else:
                markdown_by_image = {image_path: self._extract_markdown(image_path) for image_path in missing.values()}
            for page_number, image_path in missing.items():
                markdown = markdown_by_image[image_path]
                markdown_path = page_assets[page_number][1]
                markdown_path.write_text(markdown, encoding="utf-8")
                markdown_by_page[page_number] = markdown
                logger.debug("Saved MinerU markdown: page={} path={}", page_number, markdown_path)
        else:
            logger.debug("All requested MinerU pages were served from local markdown cache.")

        results: dict[int, OCRTableResult] = {}
        for page_number in unique_page_numbers:
            parse_start = perf_counter()
            image_path, markdown_path = page_assets[page_number]
            rows = self._markdown_tables_to_rows(markdown_by_page.get(page_number, ""))
            warnings: list[str] = []
            if not rows:
                warnings.append("MinerU OCR returned no HTML table blocks.")
            logger.debug(
                "Parsed MinerU markdown: page={} rows={} warnings={} elapsed={:.2f}s",
                page_number,
                len(rows),
                len(warnings),
                perf_counter() - parse_start,
            )
            results[page_number] = OCRTableResult(
                rows=rows,
                image_path=image_path,
                markdown_path=markdown_path,
                provider="MinerU",
                mode=self.mode,
                warnings=warnings,
            )
        logger.info("MinerU OCR finished in {:.2f}s", perf_counter() - start)
        return results

    def _extract_markdown(self, image_path: Path) -> str:
        from financial_claw.ocr.mineru.mineru_api import (  # type: ignore
            MinerUConfig,
            agent_extract_markdown_from_local_file,
            load_mineru_api_token,
            load_mineru_base_url,
            precision_extract_markdown_from_local_file,
        )

        base_url = load_mineru_base_url()
        if self.mode == "precision":
            token = load_mineru_api_token(_mineru_package_dir())
            cfg = MinerUConfig(base_url=base_url, api_token=token, timeout_s=60.0)
            return precision_extract_markdown_from_local_file(
                cfg,
                image_path,
                enable_table=True,
                enable_formula=True,
                is_ocr=True,
                language=self.language,
            )
        return agent_extract_markdown_from_local_file(
            base_url,
            image_path,
            enable_table=True,
            enable_formula=True,
            is_ocr=True,
            language=self.language,
        )

    def _extract_markdowns_batch(self, image_paths: list[Path]) -> dict[Path, str]:
        import httpx

        from financial_claw.ocr.mineru.mineru_api import (  # type: ignore
            MinerUConfig,
            _download_bytes,
            _raise_for_api_error,
            load_mineru_api_token,
            load_mineru_base_url,
        )

        if not image_paths:
            return {}

        base_url = load_mineru_base_url()
        token = load_mineru_api_token(_mineru_package_dir())
        cfg = MinerUConfig(base_url=base_url, api_token=token, timeout_s=60.0)
        if not cfg.api_token:
            raise RuntimeError("MINERU_API_TOKEN is required for precision mode.")

        resolved_paths = [path.expanduser().resolve() for path in image_paths]
        headers = {
            "Authorization": f"Bearer {cfg.api_token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        payload = {
            "files": [{"name": path.name} for path in resolved_paths],
            "model_version": "vlm",
            "enable_table": True,
            "enable_formula": True,
            "is_ocr": True,
            "language": self.language,
        }

        apply_url = f"{cfg.base_url}/api/v4/file-urls/batch"
        logger.debug("MinerU precision: requesting upload URLs for {} file(s)", len(resolved_paths))
        request_start = perf_counter()
        with httpx.Client(timeout=cfg.timeout_s, follow_redirects=True) as client:
            response = client.post(apply_url, headers=headers, json=payload)
            response.raise_for_status()
            resp_json = response.json()
        _raise_for_api_error(resp_json, "apply batch upload url")
        logger.debug("MinerU precision: upload URLs received in {:.2f}s", perf_counter() - request_start)

        data = resp_json.get("data") or {}
        batch_id = data.get("batch_id")
        upload_urls = data.get("file_urls") or []
        if not batch_id or len(upload_urls) != len(resolved_paths):
            raise RuntimeError(f"Unexpected MinerU batch response: {resp_json}")

        upload_start = perf_counter()
        with httpx.Client(timeout=max(cfg.timeout_s, 300.0), follow_redirects=True) as client:
            for path, upload_url in zip(resolved_paths, upload_urls):
                file_start = perf_counter()
                with path.open("rb") as f:
                    put = client.put(upload_url, content=f.read())
                put.raise_for_status()
                logger.debug(
                    "MinerU precision: uploaded {} in {:.2f}s",
                    path.name,
                    perf_counter() - file_start,
                )
        logger.debug("MinerU precision: upload phase complete in {:.2f}s", perf_counter() - upload_start)

        poll_url = f"{cfg.base_url}/api/v4/extract-results/batch/{batch_id}"
        file_names = {path.name for path in resolved_paths}
        start = time.time()
        poll_count = 0
        results_by_name: dict[str, dict] = {}
        while True:
            if time.time() - start > 600.0:
                raise TimeoutError(f"MinerU precision batch timed out after 600s (batch_id={batch_id})")
            poll_count += 1
            with httpx.Client(timeout=cfg.timeout_s, follow_redirects=True) as client:
                poll_response = client.get(poll_url, headers=headers)
                poll_response.raise_for_status()
                poll_json = poll_response.json()
            _raise_for_api_error(poll_json, "poll batch result")

            extract_results = ((poll_json.get("data") or {}).get("extract_result") or [])
            results_by_name = {
                item.get("file_name"): item
                for item in extract_results
                if item and item.get("file_name") in file_names
            }
            states = [results_by_name.get(name, {}).get("state") for name in file_names]
            logger.debug(
                "MinerU precision: poll #{} elapsed={:.1f}s states={}",
                poll_count,
                time.time() - start,
                {name: results_by_name.get(name, {}).get("state") for name in sorted(file_names)},
            )
            if any(state == "failed" for state in states):
                failed = {name: results_by_name.get(name) for name in file_names if results_by_name.get(name, {}).get("state") == "failed"}
                raise RuntimeError(f"MinerU precision batch failed: {failed}")
            if len(results_by_name) == len(file_names) and all(state == "done" for state in states):
                break
            time.sleep(2.0)

        markdown_by_path: dict[Path, str] = {}
        for path in resolved_paths:
            item = results_by_name.get(path.name) or {}
            zip_url = item.get("full_zip_url")
            if not zip_url:
                raise RuntimeError(f"MinerU result missing full_zip_url for {path.name}: {item}")
            download_start = perf_counter()
            zbytes = _download_bytes(zip_url, timeout_s=max(cfg.timeout_s, 300.0))
            markdown_by_path[path] = _read_full_markdown_from_zip(zbytes)
            logger.debug(
                "MinerU precision: downloaded and read result for {} in {:.2f}s",
                path.name,
                perf_counter() - download_start,
            )
        return markdown_by_path

    def _markdown_tables_to_rows(self, markdown: str) -> list[list[str]]:
        from financial_claw.ocr.mineru import md_table_to_excel  # type: ignore

        tables = md_table_to_excel._extract_tables(markdown)  # type: ignore[attr-defined]
        grids = [md_table_to_excel._table_cells_to_grid(table) for table in tables]  # type: ignore[attr-defined]
        rows: list[list[str]] = []
        for grid in grids:
            if rows:
                rows.append([])
            rows.extend(grid)
        return rows


def validate_mineru_configuration(*, mode: str) -> None:
    if mode not in {"precision", "agent"}:
        raise ValueError(f"Unsupported MinerU mode: {mode}")
    if mode != "precision":
        return

    from financial_claw.ocr.mineru.mineru_api import load_mineru_api_token  # type: ignore

    if not load_mineru_api_token(_mineru_package_dir()):
        raise ConfigurationError(
            f"MINERU_API_TOKEN is required for precision mode. "
            f"Set it in the environment or in src/financial_claw/ocr/mineru/.env."
        )


def _mineru_package_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "ocr" / "mineru"


def _read_full_markdown_from_zip(zbytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        names = zf.namelist()
        target = "full.md" if "full.md" in names else None
        if target is None:
            for name in names:
                if name.endswith("/full.md") or name.endswith("\\full.md"):
                    target = name
                    break
        if target is None:
            raise RuntimeError(f"Zip missing full.md. Entries: {names[:30]}")
        return zf.read(target).decode("utf-8", errors="replace")
