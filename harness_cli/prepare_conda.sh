# Sourced by the unpacked installer; does not activate or initialize Conda.
runtime_error() { printf 'harness: %s\n' "$*" >> "$install_log"; exit 1; }
data_directory=${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex
data_pending=false
for argument in "$@"; do
  if [[ "$data_pending" == true ]]; then data_directory=$argument; data_pending=false
  elif [[ "$argument" == --data-dir ]]; then data_pending=true
  elif [[ "$argument" == --data-dir=* ]]; then data_directory=${argument#*=}; fi
done
[[ "$data_pending" == false && -n "$data_directory" ]] || { printf 'Missing --data-dir value\n' >&2; exit 1; }
case "$data_directory" in '~') data_directory=$HOME ;; '~/'*) data_directory=$HOME/${data_directory:2} ;; esac
[[ "$data_directory" != *$'\n'* && "$data_directory" != *$'\r'* ]] || exit 1
while [[ "$data_directory" != / ]]; do
  case "$data_directory" in */.) data_directory=${data_directory%/.} ;; */) data_directory=${data_directory%/} ;; *) break ;; esac
  [[ -n "$data_directory" ]] || data_directory=/
done
# Home/shared-storage aliases are external locations, not managed files.
# Resolve their parent once; never follow a redirected installation root.
data_parent=$(realpath -m -- "$(dirname -- "$data_directory")")
data_directory=$data_parent/$(basename -- "$data_directory")
[[ "$data_directory" != *$'\n'* && "$data_directory" != *$'\r'* ]] || exit 1
[[ ! -L "$data_directory" ]] || { printf 'Installation root is a symlink; preserved: %s\n' "$data_directory" >&2; exit 1; }
data_directory=$(realpath -ms -- "$data_directory")
runtime_root=$data_directory-runtime
owned_runtime=()
recovery=''
# An atomic directory claim also works on shared storage without a flock helper.
mkdir -p -- "$data_parent"
runtime_lock_path=$runtime_root.bootstrap-lock
mkdir -- "$runtime_lock_path" 2>/dev/null || runtime_error "Runtime setup lock exists: $runtime_lock_path. Another installer may be running; inspect it before retrying."
runtime_lock_identity=$(stat -c '%d:%i' -- "$runtime_lock_path")
runtime_lock_owned=true
[[ ! -L "$data_directory" ]] || runtime_error "Installation root is a symlink; preserved: $data_directory"
environment_selector=(-n harness)
# A fresh tool gets an exact prefix. Never create by a name that could select
# and remove an environment belonging to another Conda installation.
if [[ ! -f "$data_directory/active.json" || -f "$data_directory/runtime.json" || -f "$runtime_root/.harness-runtime-owner" ]]; then
  for managed in "$runtime_root/conda" "$runtime_root/envs" "$runtime_root/envs/harness" "$runtime_root/envs/harness/conda-meta" "$runtime_root/envs/harness/conda-meta/history"; do
    [[ ! -L "$managed" ]] || runtime_error "Runtime path is a symlink; preserved: $managed"
  done
  if [[ -e "$runtime_root" || -L "$runtime_root" ]]; then
    [[ ! -L "$runtime_root" && -d "$runtime_root" && ! -L "$runtime_root/.harness-runtime-owner" && -f "$runtime_root/.harness-runtime-owner" ]] || runtime_error "Unowned or redirected runtime directory preserved: $runtime_root"
    expected=$(printf 'harness-codex runtime v1\n%s\n' "$data_directory")
    if [[ $(cat -- "$runtime_root/.harness-runtime-owner") != "$expected" ]]; then
      # A shared home can have a different mount prefix on another server.
      # Validate recorded ownership through current source; never rewrite Conda.
      [[ -f "$data_directory/active.json" && -f "$data_directory/runtime.json" && -f "$runtime_root/envs/harness/conda-meta/history" ]] || runtime_error "Runtime ownership does not match this installation; preserved: $runtime_root"
      timeout 10 "$runtime_root/envs/harness/bin/python" -B -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from harness_cli import distribution, footprint; footprint.inspect(distribution._read_json(Path(sys.argv[2]) / "runtime.json"), Path(sys.argv[2]))' "$source_dir" "$data_directory" >> "$install_log" 2>&1 || { printf 'Moved runtime could not be verified; preserve it and review the installation log.\n' >&2; exit 1; }
    fi
  else
    runtime_parent=$(dirname -- "$runtime_root")
    if [[ ! -d "$runtime_parent" ]]; then mkdir -p -- "$runtime_parent"; fi
    mkdir -- "$runtime_root"
    printf 'harness-codex runtime v1\n%s\n' "$data_directory" > "$runtime_root/.harness-runtime-owner"
  fi
  environment_selector=(--prefix "$runtime_root/envs/harness")
  owned_runtime=(--owned-runtime "$runtime_root")
  if [[ ! -f "$runtime_root/envs/harness/conda-meta/history" && ( -e "$runtime_root/envs/harness" || -e "$runtime_root/.harness-runtime-files.json" || -L "$runtime_root/.harness-runtime-files.json" || ( -e "$runtime_root/conda" && ! -x "$runtime_root/conda/bin/conda" ) ) ]]; then
    # Uninstall deliberately retains unknown files. Preserve the entire orphan
    # (including its old receipt) outside the fresh runtime before recreating it.
    for recorded in "$data_directory/active.json" "$data_directory/runtime.json" "$data_directory/.install.lock"; do
      [[ ! -e "$recorded" && ! -L "$recorded" ]] || runtime_error "Incomplete runtime belongs to an existing installation; preserved: $runtime_root. Missing Conda history; inspect $recorded before repairing."
    done
    recovery=$(mktemp -d "$runtime_root.recovery.XXXXXXXX")
    mv -T -- "$runtime_root" "$recovery/runtime"
    printf 'Preserved incomplete Harness runtime: %s\n' "$recovery/runtime" >> "$install_log"
    mkdir -- "$runtime_root"
    printf 'harness-codex runtime v1\n%s\n' "$data_directory" > "$runtime_root/.harness-runtime-owner"
  fi
fi
direct_runtime=false
if [[ ${#owned_runtime[@]} -gt 0 && -f "$runtime_root/envs/harness/conda-meta/history" && -x "$runtime_root/envs/harness/bin/python" ]]; then direct_runtime=true; fi
conda_command=${CONDA_EXE:-}
if [[ -n ${recovery:-} && "$conda_command" == "$runtime_root/"* ]]; then conda_command=''; fi
if [[ -z "$conda_command" && -x "$runtime_root/conda/bin/conda" ]]; then conda_command=$runtime_root/conda/bin/conda; fi
if [[ -z "$conda_command" ]]; then conda_command=$(command -v conda || true); fi
if [[ -z "$conda_command" ]]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex-conda/bin/conda"; do
    if [[ -x "$candidate" ]]; then conda_command=$candidate; break; fi
  done
fi
if [[ -z "$conda_command" && "$direct_runtime" == false ]]; then
  [[ $(uname -s) == Linux ]] || { printf '%s\n' 'Automatic Conda setup supports Linux only; set CONDA_EXE to an existing installation.' >&2; exit 1; }
  case $(uname -m) in
    x86_64) arch=x86_64; digest=14db468222ad564658656f769506056209b6dc375f5e7dfd31eb5ebbf08fa529 ;;
    aarch64|arm64) arch=aarch64; digest=0391e42075a7632e9665d6e728387ee6b905f6c3e704d3513e1c1133d0d69b89 ;;
    *) printf '%s\n' 'Automatic Conda setup supports x86_64 and aarch64.' >&2; exit 1 ;;
  esac
  for prerequisite in curl sha256sum mktemp; do command -v "$prerequisite" >/dev/null || exit 1; done
  prefix="$runtime_root/conda"
  [[ ! -e "$prefix" && ! -L "$prefix" ]] || { printf '%s\n' 'Conda setup directory already exists without a usable conda command; preserve and review it.' >&2; exit 1; }
  conda_scratch=$(mktemp -d "${TMPDIR:-/tmp}/harness-codex-conda.XXXXXXXX")
  printf '      Downloading and verifying the Python environment manager...\n' >> "$install_log"
  url="https://github.com/conda-forge/miniforge/releases/download/26.5.3-0/Miniforge3-26.5.3-0-Linux-$arch.sh"
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 15 --max-time 600 --retry 2 "$url" -o "$conda_scratch/miniforge.sh" </dev/null >> "$install_log" 2>&1
  actual=$(sha256sum "$conda_scratch/miniforge.sh")
  [[ ${actual%% *} == "$digest" ]] || { printf '%s\n' 'Miniforge checksum mismatch; refusing execution.' >&2; exit 1; }
  mkdir -p -- "$(dirname -- "$prefix")"
  printf '      Installing the Python environment manager; this may take a few minutes...\n' >> "$install_log"
  bash "$conda_scratch/miniforge.sh" -b -p "$prefix" </dev/null >> "$install_log" 2>&1
  conda_command="$prefix/bin/conda"
fi
finish_step
start_step '[2/3] Preparing the isolated Harness environment'
if [[ "$direct_runtime" == false ]]; then
  environments=$("$conda_command" env list --json 2>> "$install_log")
  printf '%s\n' "$environments" >> "$install_log"
fi
if [[ ${#owned_runtime[@]} -gt 0 && ! -f "$runtime_root/envs/harness/conda-meta/history" ]]; then
  [[ ! -e "$runtime_root/envs/harness" && ! -L "$runtime_root/envs/harness" ]] || runtime_error "Incomplete runtime appeared during setup; preserved: $runtime_root/envs/harness"
  "$conda_command" create "${environment_selector[@]}" --override-channels --channel conda-forge python=3.11 git --yes >> "$install_log" 2>&1
else
  printf '      Reusing the existing Harness environment.\n' >> "$install_log"
fi
if [[ ${#owned_runtime[@]} -gt 0 ]]; then
  selected_prefix="$runtime_root/envs/harness"
else
  # Resolve the environment selected by Conda, never the caller's active base.
  # An absolute shell remains reliable when system directories precede Conda.
  selected_prefix=$("$conda_command" run --no-capture-output "${environment_selector[@]}" /bin/sh -c 'printf "%s\n" "$CONDA_PREFIX"' 2>> "$install_log")
fi
[[ "$selected_prefix" == /* && -f "$selected_prefix/conda-meta/history" ]] || { printf 'Unable to resolve the selected Harness environment.\n' >&2; exit 1; }
selected_prefix=$(realpath -e -- "$selected_prefix")
selected_python="$selected_prefix/bin/python"
[[ -x "$selected_python" ]] || { printf 'Selected environment has no executable Python: %s\n' "$selected_python" >&2; exit 1; }
resolved_python=$(realpath -e -- "$selected_python")
[[ "$resolved_python" == "$selected_prefix/"* ]] || { printf 'Selected Python resolves outside its environment; installation stopped.\n' >&2; exit 1; }
environment_selector=(--prefix "$selected_prefix")
installer_runner=("$conda_command" run --no-capture-output "${environment_selector[@]}")
if [[ "$direct_runtime" == true ]]; then
  installer_runner=()
  timeout 10 "$selected_python" -B -c 'import json, ssl, sqlite3, sys; from pathlib import Path; assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(), "Moved interpreter prefix mismatch"' "$selected_prefix" >> "$install_log" 2>&1 || { printf 'The existing interpreter cannot run at this mount. Its files were preserved.\n' >&2; exit 1; }
fi
printf 'Expected interpreter: %s\nExpected prefix: %s\n' "$selected_python" "$selected_prefix" >> "$install_log"
if ! command -v git >/dev/null 2>&1 && ! "$selected_prefix/bin/git" --version >> "$install_log" 2>&1; then
  printf '      Preparing Git for tool updates...\n' >> "$install_log"
  "$conda_command" install "${environment_selector[@]}" --override-channels --channel conda-forge git --yes >> "$install_log" 2>&1
fi
finish_step
