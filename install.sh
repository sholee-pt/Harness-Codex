#!/usr/bin/env bash
# Install an unpacked Codex release with an isolated interpreter and Bash PATH registration.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf '%s\n' 'Usage: bash install.sh [--agent codex] [--bin-dir PATH] [--data-dir PATH] [--branch codex/vN.M] [--repository URL] [--auto-update compatible|check|off] [--no-modify-path]' 'Reuses Conda or installs checksum-pinned Miniforge on Linux. Prepares the dedicated harness environment.' 'Installs harness-codex without sudo; registers PATH in ~/.bashrc unless --no-modify-path is supplied.'
  exit 0
fi
runtime=codex
selected_runtime=''
select_runtime() {
  if [[ -z "$1" ]]; then
    printf '%s\n' 'Missing value for --agent.' >&2
    exit 1
  fi
  if [[ -n "$selected_runtime" && "$selected_runtime" != "$1" ]]; then
    printf '%s\n' 'Conflicting --agent/--runtime selections; choose one agent provider.' >&2
    exit 1
  fi
  selected_runtime=$1
  runtime=$1
}
runtime_value_pending=false
for argument in "$@"; do
  if [[ "$runtime_value_pending" == true ]]; then
    select_runtime "$argument"
    runtime_value_pending=false
  elif [[ "$argument" == --agent || "$argument" == --runtime ]]; then
    runtime_value_pending=true
  elif [[ "$argument" == --agent=* || "$argument" == --runtime=* ]]; then
    select_runtime "${argument#*=}"
  fi
done
if [[ "$runtime_value_pending" == true || "$runtime" != codex ]]; then
  printf '%s\n' 'Only --agent codex is supported. Claude integration is not implemented; no environment was prepared.' >&2
  exit 1
fi
source "$source_dir/harness_cli/prepare_conda.sh"
"$conda_command" run --no-capture-output -n harness python -B "$source_dir/harness.py" install "$@"
