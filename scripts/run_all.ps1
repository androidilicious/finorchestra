# One command from a clean checkout to a finished report (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1
# Optional: -Llm openai_compatible -Model qwen2.5:3b -BaseUrl http://localhost:11434/v1 -Start 2025-01-03
param(
    [string]$Llm = "mock",
    [string]$Model = "",
    [string]$BaseUrl = "",
    [string]$Start = "",
    [string]$End = "",
    [string]$Name = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    uv venv --python 3.13 .venv
}
uv pip install --python .venv -q -e ".[dev]"

& .venv\Scripts\python -m finorchestra.cli pull
& .venv\Scripts\python -m pytest tests -q

$args_ = @("-m", "finorchestra.cli", "run", "--llm", $Llm)
if ($Model)   { $args_ += @("--model", $Model) }
if ($BaseUrl) { $args_ += @("--base-url", $BaseUrl) }
if ($Start)   { $args_ += @("--start", $Start) }
if ($End)     { $args_ += @("--end", $End) }
if ($Name)    { $args_ += @("--name", $Name) }
& .venv\Scripts\python @args_
