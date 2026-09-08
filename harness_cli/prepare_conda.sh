# Sourced by the unpacked installer; does not activate or initialize Conda.
conda_command=${CONDA_EXE:-}
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
  prefix="${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex-conda"
  [[ ! -e "$prefix" && ! -L "$prefix" ]] || { printf '%s\n' 'Conda setup directory already exists without a usable conda command; preserve and review it.' >&2; exit 1; }
  conda_scratch=$(mktemp -d "${TMPDIR:-/tmp}/harness-codex-conda.XXXXXXXX")
  printf '      Downloading and verifying the Python environment manager...\n'
  url="https://github.com/conda-forge/miniforge/releases/download/26.5.3-0/Miniforge3-26.5.3-0-Linux-$arch.sh"
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 15 --max-time 600 --retry 2 "$url" -o "$conda_scratch/miniforge.sh" </dev/null >> "$install_log" 2>&1
  actual=$(sha256sum "$conda_scratch/miniforge.sh")
  [[ ${actual%% *} == "$digest" ]] || { printf '%s\n' 'Miniforge checksum mismatch; refusing execution.' >&2; exit 1; }
  mkdir -p -- "$(dirname -- "$prefix")"
  printf '      Installing the Python environment manager; this may take a few minutes...\n'
  bash "$conda_scratch/miniforge.sh" -b -p "$prefix" </dev/null >> "$install_log" 2>&1
  conda_command="$prefix/bin/conda"
fi
finish_step
start_step '[2/3] Preparing the isolated Harness environment'
environments=$("$conda_command" env list --json 2>> "$install_log")
printf '%s\n' "$environments" >> "$install_log"
if ! printf '%s' "$environments" | grep -Eq '"[^"]*/harness"'; then
  printf '      First setup: preparing Python and Git; this may take a few minutes...\n'
  "$conda_command" create --name harness --override-channels --channel conda-forge python=3.11 git --yes >> "$install_log" 2>&1
else
  printf '      Reusing the existing Harness environment.\n'
fi
if ! command -v git >/dev/null 2>&1 && ! "$conda_command" run -n harness git --version >> "$install_log" 2>&1; then
  printf '      Preparing Git for tool updates...\n'
  "$conda_command" install --name harness --override-channels --channel conda-forge git --yes >> "$install_log" 2>&1
fi
finish_step
