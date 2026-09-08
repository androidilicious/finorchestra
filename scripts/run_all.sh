#!/usr/bin/env bash
# One command from a clean checkout to a finished report (macOS / Linux / Git Bash).
#   bash scripts/run_all.sh
#   LLM=openai_compatible MODEL=qwen2.5:3b BASE_URL=http://localhost:11434/v1 START=2025-01-03 bash scripts/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || uv venv --python 3.13 .venv
uv pip install --python .venv -q -e ".[dev]"
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python

"$PY" -m finorchestra.cli pull
"$PY" -m pytest tests -q

args=(-m finorchestra.cli run --llm "${LLM:-mock}")
[ -n "${MODEL:-}" ]    && args+=(--model "$MODEL")
[ -n "${BASE_URL:-}" ] && args+=(--base-url "$BASE_URL")
[ -n "${START:-}" ]    && args+=(--start "$START")
[ -n "${END:-}" ]      && args+=(--end "$END")
[ -n "${NAME:-}" ]     && args+=(--name "$NAME")
"$PY" "${args[@]}"
