## MinerU

Small helpers around MinerU Open API to extract markdown (often containing HTML `<table>` blocks) from local images/PDFs, then optionally convert those tables into Excel.

### Files

- `mineru_api.py`: Minimal client helpers for MinerU “agent” and “precision” flows.
- `extract_table_from_image.py`: Extract markdown from an image, and optionally dump detected `<table>...</table>` blocks to HTML.
- `extract_table_image_to_excel.py`: Extract markdown from an image and write extracted tables into an `.xlsx` file.
- `md_table_to_excel.py`: Convert markdown-embedded HTML tables into `.xlsx` (standalone converter).

### Env / secrets

- Put your token in `mineru/.env` (ignored by git) as `MINERU_API_TOKEN=...`
- Or export `MINERU_API_TOKEN` in your shell.

### Quick usage

```bash
# Extract markdown (precision mode needs token)
python -m mineru.extract_table_from_image --image path/to/img.png --mode precision

# Extract tables directly into xlsx
python -m mineru.extract_table_image_to_excel --image path/to/img.png --mode precision --out-xlsx out.xlsx
```

