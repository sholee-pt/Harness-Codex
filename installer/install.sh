#!/usr/bin/env bash
# Install an unpacked Codex release with an isolated interpreter and Bash PATH registration.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -f "$source_dir/harness.py" ]]; then
  source_dir="$(cd -- "$source_dir/.." && pwd -P)"
fi
for argument in "$@"; do
if [[ "$argument" == "--help" || "$argument" == "-h" ]]; then
  printf '%s\n' 'Usage: bash install.sh [--bin-dir PATH] [--data-dir PATH] [--branch vX.Y.Z-beta] [--repository URL] [--auto-update compatible|check|off] [--existing ask|reuse|reset] [--no-modify-path] [--no-codex-integration] [--activate ask|shell|skip]' 'Reuses Conda or installs checksum-pinned Miniforge on Linux. Prepares the dedicated harness environment.' 'Installs harness-codex and official Codex integration without sudo; registers PATH in ~/.bashrc unless --no-modify-path is supplied.'
  exit 0
fi
done
activate=ask
arguments=()
data_directory=${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex
bin_directory=$HOME/.local/bin
selected_branch=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-modify-path|--no-codex-integration) arguments+=("$1"); shift; continue ;;
    --activate|--data-dir|--bin-dir|--branch|--repository|--auto-update|--existing|--agent|--runtime)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { printf 'Missing %s value\n' "$1" >&2; exit 1; }
      key=$1; value=$2; shift 2 ;;
    --activate=*|--data-dir=*|--bin-dir=*|--branch=*|--repository=*|--auto-update=*|--existing=*|--agent=*|--runtime=*)
      key=${1%%=*}; value=${1#*=}; shift
      [[ -n "$value" ]] || { printf 'Missing %s value\n' "$key" >&2; exit 1; } ;;
    *) printf 'Unknown option: %s. Use --help.\n' "$1" >&2; exit 1 ;;
  esac
  case "$key" in
    --activate) activate=$value; continue ;;
    --data-dir) data_directory=$value ;;
    --bin-dir) bin_directory=$value ;;
    --auto-update) case "$value" in compatible|check|off) ;; *) printf 'Invalid automatic update policy\n' >&2; exit 1 ;; esac ;;
    --existing) case "$value" in ask|reuse|reset) ;; *) printf 'Invalid existing-installation choice\n' >&2; exit 1 ;; esac ;;
    --branch) [[ "$value" =~ ^(codex/)?v(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)(-beta)?)?)?$ ]] || { printf 'Invalid version branch\n' >&2; exit 1; }; selected_branch=$value ;;
    --repository) case "${value%.git}" in
      https://github.com/sholee-pt/Harness|https://github.com/sholee-pt/Harness-Codex|git@github.com:sholee-pt/Harness|git@github.com:sholee-pt/Harness-Codex|ssh://git@github.com/sholee-pt/Harness|ssh://git@github.com/sholee-pt/Harness-Codex) ;;
      *) printf 'Select the Harness-Codex repository\n' >&2; exit 1 ;; esac ;;
  esac
  arguments+=("$key" "$value")
done
case "$activate" in ask|shell|skip) ;; *) printf 'Invalid --activate choice; use ask, shell or skip\n' >&2; exit 1 ;; esac
set -- "${arguments[@]}"
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
if [[ -n "$selected_branch" ]]; then
  metadata=$source_dir/.agents/skills/harness/scripts/harness_metadata.py
  [[ -f "$metadata" ]] || { printf 'Source version metadata is missing\n' >&2; exit 1; }
  source_version=$(sed -nE "s/^HARNESS_VERSION[[:space:]]*=[[:space:]]*['\"]([^'\"]+)['\"].*/\\1/p" "$metadata")
  branch_version=${selected_branch#codex/}; branch_version=${branch_version#v}
  [[ "$branch_version" == *.* ]] || branch_version=$branch_version.0
  [[ "$branch_version" == *.*.* ]] || branch_version=0.$branch_version-beta
  [[ "$source_version" == *.*.* ]] || source_version=0.$source_version-beta
  [[ "$source_version" == "$branch_version" ]] || { printf 'Source version does not match pinned branch\n' >&2; exit 1; }
fi
preflight_path() {
  local path=$1 component candidate resolved
  local -a components
  [[ -n "$path" && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || { printf 'Invalid installation path\n' >&2; exit 1; }
  case "$path" in '~') path=$HOME ;; '~/'*) path=$HOME/${path:2} ;; esac
  # Remove only trailing separators/dots. Resolving '..' before parent aliases
  # would select a different directory from the caller's physical path.
  while [[ "$path" != / ]]; do
    case "$path" in */.) path=${path%/.} ;; */) path=${path%/} ;; *) break ;; esac
    [[ -n "$path" ]] || path=/
  done
  [[ ! -L "$path" ]] || { printf 'Installation root is a symlink; preserved: %s\n' "$path" >&2; exit 1; }
  resolved=$(realpath -m -- "$path") || { printf 'Cannot resolve installation path\n' >&2; exit 1; }
  for candidate in "$1" "$path" "$resolved"; do
    IFS=/ read -r -a components <<< "$candidate"
    for component in "${components[@]}"; do
      component=${component%"${component##*[! .]}"}
      [[ ${component,,} != .git ]] || { printf 'Installation paths must remain outside Git metadata\n' >&2; exit 1; }
    done
  done
  candidate=$resolved
  while [[ "$candidate" != / ]]; do
    [[ ! -e "$candidate" || -d "$candidate" ]] || { printf 'Installation path is not a directory; preserved: %s\n' "$candidate" >&2; exit 1; }
    candidate=$(dirname -- "$candidate")
  done
}
preflight_path "$data_directory"
case "$data_directory" in '~') data_directory=$HOME ;; '~/'*) data_directory=$HOME/${data_directory:2} ;; esac
data_directory=$(realpath -m -- "$data_directory")
preflight_path "$data_directory-runtime"
preflight_path "$bin_directory"
install_log=$(mktemp "${TMPDIR:-/tmp}/harness-codex-install-log.XXXXXXXX")
exec {installer_stderr_fd}>&2
HARNESS_INSTALL_PAUSE_FILE=$(mktemp "${TMPDIR:-/tmp}/harness-codex-progress-XXXXXXXX")
printf 'Harness installation progress\nrunning\n' > "$HARNESS_INSTALL_PAUSE_FILE"
export HARNESS_INSTALL_PAUSE_FILE
spinner_pid=''
runtime_lock_owned=false
conda_scratch=''
step='Starting installer'
step_started=$SECONDS
accent='' success='' plain=''
if [[ -t 1 && -z ${NO_COLOR:-} && ${TERM:-dumb} != dumb ]]; then
  accent=$'\033[1;36m'; success=$'\033[1;32m'; plain=$'\033[0m'
fi
start_step() {
  step=$1
  step_started=$SECONDS
  printf '\n%s\n' "$step" >> "$install_log"
  if [[ -t 1 && ${TERM:-dumb} != dumb ]]; then
    printf '\n'
    (
      frames='|/-\\'; index=0
      while true; do
        if [[ $(tail -n 1 -- "$HARNESS_INSTALL_PAUSE_FILE") != paused ]]; then
          printf '\r\033[2K  %s%s%s %s  %ss' "$accent" "${frames:index%4:1}" "$plain" "$step" "$((SECONDS - step_started))"
        fi
        index=$((index + 1)); sleep 0.2
      done
    ) &
    spinner_pid=$!
  else
    printf '\n%s' "$step"
  fi
}
stop_spinner() {
  if [[ -n "$spinner_pid" ]]; then
    kill "$spinner_pid" 2>/dev/null || true
    wait "$spinner_pid" 2>/dev/null || true
    spinner_pid=''
    printf '\r\033[2K'
  fi
}
finish_step() {
  if [[ -n "$spinner_pid" ]]; then stop_spinner; printf '%s' "$step"; fi
  printf ': done (%ss)  %sOK%s\n' "$((SECONDS - step_started))" "$success" "$plain"
}
release_runtime_lock() {
  if [[ ${runtime_lock_owned:-false} == true && ! -L "$runtime_lock_path" && $(stat -c '%d:%i' -- "$runtime_lock_path" 2>/dev/null) == "$runtime_lock_identity" ]]; then
    rmdir -- "$runtime_lock_path" || printf 'Runtime setup lock was changed; preserved: %s\n' "$runtime_lock_path" >&2
    runtime_lock_owned=false
  fi
}
finish_install() {
  local result=$?
  exec 2>&"$installer_stderr_fd"
  exec {installer_stderr_fd}>&-
  stop_spinner
  release_runtime_lock
  rm -f -- "$HARNESS_INSTALL_PAUSE_FILE"
  if [[ -n "$conda_scratch" ]]; then rm -rf -- "$conda_scratch"; fi
  if [[ "$result" -ne 0 ]]; then
    printf '\n%s: failed (exit %s). Last log lines:\n' "$step" "$result" >&2
    sed -n '/^harness:/p' "$install_log" >&2
    sed -n '/^Preserved incomplete Harness runtime:/p' "$install_log" >&2
    tail -n 15 -- "$install_log" | sed '/^harness:/d; /^Preserved incomplete Harness runtime:/d' >&2
    printf 'Detailed log: %s\n' "$install_log" >&2
  fi
  exit "$result"
}
trap finish_install EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '\n%sHarness for Codex installer%s\n================================\nDetailed log: %s\n' "$accent" "$plain" "$install_log"
start_step '[1/3] Checking installation tools'
source "$source_dir/harness_cli/prepare_conda.sh" 2>> "$install_log"
start_step '[3/3] Installing command and applying PATH preferences'
# Prepare the transport before the CLI seals a newly owned runtime receipt.
# Later dependency files must not be mistaken for unrelated user additions.
prepare_integration=true
for argument in "$@"; do
  case "$argument" in --no-modify-path|--no-codex-integration) prepare_integration=false ;; esac
done
if [[ "$prepare_integration" == true && "$(uname -s)" == Linux ]]; then
  "${installer_runner[@]}" "$selected_python" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from harness_cli.auto_relay import dependency; dependency(install=True)' "$source_dir" >> "$install_log" 2>&1
fi
HARNESS_INSTALL_EXPECTED_PREFIX="$selected_prefix" "${installer_runner[@]}" "$selected_python" -B "$source_dir/harness.py" install "$@" "${owned_runtime[@]}" >> "$install_log" 2>&1
finish_step
release_runtime_lock
# Keep the CLI receipt contract intact; replay only its existing human summary.
sed -n '/^Preserved incomplete Harness runtime:/p' "$install_log"
sed -n '/^Installed /p' "$install_log"
sed -n '/^Ready: /p' "$install_log"
printf 'Installation complete. Detailed log: %s\n' "$install_log"
# A child installer cannot mutate its parent Bash. With explicit consent, open
# an interactive child that actually reads the configured ~/.bashrc.
modify_path=true
for argument in "$@"; do [[ "$argument" != --no-modify-path ]] || modify_path=false; done
if [[ "$activate" != skip && "$modify_path" == true && -t 1 && -r /dev/tty && -w /dev/tty ]]; then
  open_shell=false
  if [[ "$activate" == shell ]]; then open_shell=true
  else
    printf '\nThis is a child shell; exit returns to your original shell.\n' > /dev/tty
    while true; do
      printf 'Open a new Bash with ~/.bashrc loaded now? [Y/n]: ' > /dev/tty
      IFS= read -r answer < /dev/tty || break
      answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      case "$answer" in
        ''|yes|y) open_shell=true; break ;;
        no|n) break ;;
        *) printf 'Press Enter or type y/yes to approve; type n/no to decline.\n' > /dev/tty ;;
      esac
    done
  fi
  if [[ "$open_shell" == true ]]; then
    printf 'Opening Bash with ~/.bashrc applied. Try: harness-codex --version\n'
    # Do not leak installer control state into the new project shell.
    if ! env -u HARNESS_INSTALL_PAUSE_FILE bash --rcfile "$HOME/.bashrc" -i < /dev/tty > /dev/tty 2>&1; then
      printf 'The child Bash exited with an error. Harness remains installed.\n'
    fi
  fi
fi
