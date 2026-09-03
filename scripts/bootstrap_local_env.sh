#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_root="${STOCK_VENV_ROOT:-${HOME}/.virtualenvs}"

"${python_bin}" -c 'import sys; expected=(3, 12); actual=sys.version_info[:2]; raise SystemExit(0 if actual == expected else f"Python 3.12 is required, got {actual[0]}.{actual[1]}")'

if command -v scutil >/dev/null 2>&1; then
    machine_name="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
else
    machine_name="$(hostname -s)"
fi
machine_name="$(printf '%s' "${machine_name}" | tr -cd '[:alnum:]_-')"
venv_dir="${venv_root}/stock-${machine_name}-py312"

if [[ "${1:-}" == "--print-path" ]]; then
    printf '%s\n' "${venv_dir}"
    exit 0
fi

mkdir -p "${venv_root}"
"${python_bin}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install -r "${project_root}/requirements.lock"
"${venv_dir}/bin/python" -m pip install --no-deps -e "${project_root}"

printf 'Local environment ready: %s\n' "${venv_dir}"
printf 'Run research with: %s/bin/python %s/scripts/korean_stock_research.py 005930 --enhanced --verbose\n' "${venv_dir}" "${project_root}"
