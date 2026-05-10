$ErrorActionPreference = "Stop"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "src;$env:PYTHONPATH" } else { "src" }

Get-ChildItem -Path "companies" -Directory | ForEach-Object {
    python -m financial_claw.pipeline.ingest $_.Name --companies-root companies --max-workers 8 --ocr-provider mineru --mineru-mode precision
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
