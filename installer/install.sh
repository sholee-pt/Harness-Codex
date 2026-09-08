#!/usr/bin/env bash
# Install an unpacked Codex release with an isolated interpreter and Bash PATH registration.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -f "$source_dir/harness.py" ]]; then
  source_dir="$(cd -- "$source_dir/.." && pwd -P)"
fi
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
[[ -f "$source_dir/harness.py" ]] || { printf '%s\n' 'Run install.sh from a complete Harness source archive.' >&2; exit 1; }
install_log=$(mktemp "${TMPDIR:-/tmp}/harness-codex-install-log.XXXXXXXX")
conda_scratch=''
step='Starting installer'
step_started=$SECONDS
start_step() {
  step=$1
  step_started=$SECONDS
  printf '%s...\n' "$step"
  printf '\n%s\n' "$step" >> "$install_log"
}
finish_step() { printf '%s: done (%ss)\n' "$step" "$((SECONDS - step_started))"; }
finish_install() {
  local result=$?
  if [[ -n "$conda_scratch" ]]; then rm -rf -- "$conda_scratch"; fi
  if [[ "$result" -ne 0 ]]; then
    printf '\n%s: failed (exit %s). Last log lines:\n' "$step" "$result" >&2
    tail -n 15 -- "$install_log" >&2
    printf 'Detailed log: %s\n' "$install_log" >&2
  fi
  exit "$result"
}
trap finish_install EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Harness for Codex installer\nDetailed log: %s\n' "$install_log"
start_step '[1/3] Checking installation tools'
source "$source_dir/harness_cli/prepare_conda.sh"
start_step '[3/3] Installing command and applying PATH preferences'
"$conda_command" run --no-capture-output -n harness python -B "$source_dir/harness.py" install "$@" >> "$install_log" 2>&1
finish_step
# Keep the CLI receipt contract intact; replay only its existing human summary.
sed -n '/^Installed /p' "$install_log"
printf 'Installation complete. Detailed log: %s\n' "$install_log"
