# Sourced by the unpacked installer; does not activate or initialize Conda.
data_directory=${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex
data_pending=false
for argument in "$@"; do
  if [[ "$data_pending" == true ]]; then data_directory=$argument; data_pending=false
  elif [[ "$argument" == --data-dir ]]; then data_pending=true
  elif [[ "$argument" == --data-dir=* ]]; then data_directory=${argument#*=}; fi
done
[[ "$data_pending" == false && -n "$data_directory" ]] || { printf 'Missing --data-dir value\n' >&2; exit 1; }
[[ "$data_directory" != *$'\n'* && "$data_directory" != *$'\r'* ]] || exit 1
# Home/shared-storage aliases are external locations, not managed files.
# Resolve their parent once; never follow a redirected installation root.
data_parent=$(realpath -m -- "$(dirname -- "$data_directory")")
data_directory=$data_parent/$(basename -- "$data_directory")
[[ "$data_directory" != *$'\n'* && "$data_directory" != *$'\r'* ]] || exit 1
[[ ! -L "$data_directory" ]] || { printf 'Installation root is a symlink; preserved: %s\n' "$data_directory" >&2; exit 1; }
data_directory=$(realpath -ms -- "$data_directory")
runtime_root=$data_directory-runtime
owned_runtime=()
environment_selector=(-n harness)
# A fresh tool gets an exact prefix. Never create by a name that could select
# and remove an environment belonging to another Conda installation.
if [[ ! -f "$data_directory/active.json" || -f "$data_directory/runtime.json" || -f "$runtime_root/.harness-runtime-owner" ]]; then
  if [[ -e "$runtime_root" || -L "$runtime_root" ]]; then
    [[ ! -L "$runtime_root" && -f "$runtime_root/.harness-runtime-owner" ]] || { printf 'Unowned runtime directory preserved: %s\n' "$runtime_root" >&2; exit 1; }
    expected=$(printf 'harness-codex runtime v1\n%s\n' "$data_directory")
    [[ $(cat -- "$runtime_root/.harness-runtime-owner") == "$expected" ]] || { printf 'Runtime belongs to another installation\n' >&2; exit 1; }
  else
    runtime_parent=$(dirname -- "$runtime_root")
    if [[ ! -d "$runtime_parent" ]]; then mkdir -p -- "$runtime_parent"; fi
    mkdir -- "$runtime_root"
    printf 'harness-codex runtime v1\n%s\n' "$data_directory" > "$runtime_root/.harness-runtime-owner"
  fi
  environment_selector=(--prefix "$runtime_root/envs/harness")
  owned_runtime=(--owned-runtime "$runtime_root")
fi
conda_command=${CONDA_EXE:-}
if [[ -z "$conda_command" && -x "$runtime_root/conda/bin/conda" ]]; then conda_command=$runtime_root/conda/bin/conda; fi
if [[ -z "$conda_command" ]]; then conda_command=$(command -v conda || true); fi
if [[ -z "$conda_command" ]]; then
  for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex-conda/bin/conda"; do
    if [[ -x "$candidate" ]]; then conda_command=$candidate; break; fi
  done
fi
if [[ -z "$conda_command" ]]; then
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
environments=$("$conda_command" env list --json 2>> "$install_log")
printf '%s\n' "$environments" >> "$install_log"
if [[ ${#owned_runtime[@]} -gt 0 && ! -f "$runtime_root/envs/harness/conda-meta/history" ]]; then
  [[ ! -e "$runtime_root/envs/harness" ]] || { printf 'Incomplete runtime environment preserved; inspect it before reinstalling.\n' >&2; exit 1; }
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
printf 'Expected interpreter: %s\nExpected prefix: %s\n' "$selected_python" "$selected_prefix" >> "$install_log"
if ! command -v git >/dev/null 2>&1 && ! "$conda_command" run "${environment_selector[@]}" git --version >> "$install_log" 2>&1; then
  printf '      Preparing Git for tool updates...\n' >> "$install_log"
  "$conda_command" install "${environment_selector[@]}" --override-channels --channel conda-forge git --yes >> "$install_log" 2>&1
fi
finish_step
