#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"

for company_dir in companies/*; do
  [ -d "$company_dir" ] || continue
  company="$(basename "$company_dir")"
  python -m financial_claw.pipeline.ingest "$company" init \
    --companies-root companies \
    --max-workers 8 \
    --ocr-provider mineru \
    --mineru-mode precision
done
