$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = Join-Path $repoRoot "desktop\FinancialClaw.Desktop\FinancialClaw.Desktop.csproj"

Set-Location $repoRoot
dotnet run --project $projectPath
