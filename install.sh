#!/usr/bin/env bash
# Install an unpacked Harness release without sudo or modifying shell startup files.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  printf '%s\n' 'Usage: bash install.sh [--agent codex] [--bin-dir PATH] [--data-dir PATH] [--branch codex/vN.M] [--repository URL] [--auto-update compatible|check|off]' 'Requires Anaconda or Miniconda. Creates the dedicated harness environment if absent.' 'Installs the harness command for the current user; no sudo or shell profile edits.'
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
conda_command="${CONDA_EXE:-}"
if [[ -z "$conda_command" ]]; then
  conda_command="$(command -v conda || true)"
fi
if [[ -z "$conda_command" ]]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
    if [[ -x "$candidate" ]]; then conda_command="$candidate"; break; fi
  done
fi
if [[ -z "$conda_command" ]]; then
  printf '%s\n' 'Anaconda or Miniconda was not found. Install one and rerun bash install.sh, or set CONDA_EXE to its conda executable.' >&2
  exit 1
fi
# Conda's Linux JSON environment paths end in the environment name.
environments="$("$conda_command" env list --json)"
if ! printf '%s' "$environments" | grep -Eq '"[^"]*/harness"'; then
  "$conda_command" env create --file "$source_dir/environment.yml" --yes
fi
"$conda_command" run --no-capture-output -n harness python -B "$source_dir/harness.py" install "$@"
