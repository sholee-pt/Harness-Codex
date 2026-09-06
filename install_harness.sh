#!/usr/bin/env bash
# Download a pinned Harness source revision, then delegate to its owned installer.
# Disable tracing before reading credentials, including when invoked with bash -x.
set +x
set -euo pipefail
IFS=$' \t\n'

usage() {
  printf '%s\n' \
    'Usage: bash install_harness.sh [OPTIONS]' \
    '  --runtime codex|claude       Codex is supported; Claude is not yet supported.' \
    '  --branch codex/vN[.M]        Pin a branch; otherwise select the latest Codex version.' \
    '  --repository URL            Harness HTTPS or SSH transport; default tries HTTPS, then SSH.' \
    '  --bin-dir PATH              Forward to the user-local tool installer.' \
    '  --data-dir PATH             Forward to the user-local tool installer.' \
    '  --auto-update POLICY        compatible (default), check, or off.' \
    '  --help                      Show this help without network or filesystem changes.' \
    '' \
    'Requires Bash, Git, tar, and Anaconda/Miniconda. The source installer prepares the harness environment.' \
    'For this private repository, use existing Git credentials, GITHUB_TOKEN/GH_TOKEN, or a configured SSH key.' \
    'Git author name/email do not authenticate downloads. This script never changes Git credentials or project files.' \
    'OpenSSH key/agent settings are preserved; passphrase prompts are disabled. Custom SSH wrappers must be noninteractive.'
}

fail() { printf 'Harness bootstrap: %s\n' "$*" >&2; exit 1; }
need_value() { [[ $# -ge 2 && -n "$2" ]] || fail "Missing value for $1."; }

runtime=codex
branch=''
repository=''
forward=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --runtime) need_value "$@"; runtime=$2; shift 2 ;;
    --runtime=*) runtime=${1#*=}; shift ;;
    --branch) need_value "$@"; branch=$2; shift 2 ;;
    --branch=*) branch=${1#*=}; shift ;;
    --repository) need_value "$@"; repository=$2; shift 2 ;;
    --repository=*) repository=${1#*=}; shift ;;
    --bin-dir|--data-dir|--auto-update)
      need_value "$@"; forward+=("$1" "$2"); shift 2 ;;
    --bin-dir=*|--data-dir=*|--auto-update=*)
      flag=${1%%=*}; value=${1#*=}; [[ -n "$value" ]] || fail "Missing value for $flag."
      forward+=("$flag" "$value"); shift ;;
    *) fail "Unknown option: $1. Use --help." ;;
  esac
done

case "$runtime" in
  codex) ;;
  claude) fail 'Claude support is not implemented in this installer. The existing claude/v2 branch uses its separate legacy skill installation.' ;;
  *) fail 'Runtime must be codex or claude; currently only Codex is supported.' ;;
esac
branch_pattern='^codex/v(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$'
[[ -z "$branch" || "$branch" =~ $branch_pattern ]] || fail 'Branch must be codex/vN or codex/vN.M.'
https_repository='https://github.com/sholee-pt/Harness.git'
ssh_repository='git@github.com:sholee-pt/Harness.git'
case "$repository" in
  ''|"$https_repository"|"$ssh_repository"|'ssh://git@github.com/sholee-pt/Harness.git') ;;
  *) fail 'Only the sholee-pt/Harness repository using its exact HTTPS or SSH transport is supported.' ;;
esac
for ((index=0; index<${#forward[@]}; index+=2)); do
  if [[ ${forward[index]} == --auto-update ]]; then
    case "${forward[index+1]}" in compatible|check|off) ;; *) fail 'Automatic update policy must be compatible, check, or off.' ;; esac
  fi
done

token_available=false
if [[ -n ${GITHUB_TOKEN:-} || -n ${GH_TOKEN:-} ]]; then
  token_value=${GITHUB_TOKEN:-${GH_TOKEN:-}}
  [[ ! "$token_value" =~ [[:cntrl:]] ]] || fail 'The GitHub token contains unsupported control characters.'
  unset token_value
  token_available=true
fi
for prerequisite in git tar mktemp chmod rm mkdir cat bash; do
  command -v "$prerequisite" >/dev/null 2>&1 || fail "Required command is missing: $prerequisite."
done

# Only this uniquely created temporary directory is recursively cleaned.
scratch_parent=${TMPDIR:-/tmp}
[[ -d "$scratch_parent" ]] || fail 'The temporary directory does not exist.'
scratch_parent=$(cd -- "$scratch_parent" && pwd -P)
temporary=$(mktemp -d "$scratch_parent/harness-bootstrap.XXXXXXXX")
cleanup() {
  if [[ -n ${temporary:-} && "$temporary" == "$scratch_parent"/harness-bootstrap.* && -d "$temporary" ]]; then
    rm -rf -- "$temporary"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# This helper contains no credentials. Git supplies the prompt, and the helper
# reads the token only from the inherited environment for the fixed GitHub origin.
cat > "$temporary/askpass.sh" <<'ASKPASS'
#!/usr/bin/env bash
set +x
set -eu
prompt=${1:-}
username="^Username for 'https://github[.]com(/sholee-pt/Harness([.]git)?)?': ?$"
password="^Password for 'https://x-access-token@github[.]com(/sholee-pt/Harness([.]git)?)?': ?$"
if [[ "$prompt" =~ $username ]]; then
  printf '%s\n' x-access-token
elif [[ "$prompt" =~ $password ]]; then
  printf '%s\n' "${GITHUB_TOKEN:-${GH_TOKEN:-}}"
else
  exit 1
fi
ASKPASS
chmod 700 "$temporary/askpass.sh"
mkdir "$temporary/empty-template"

git_run() {
  local transport=$1
  shift
  (
    # Contain Git context/configuration injection to the download subprocess.
    # User credential helpers and ordinary SSH configuration remain available.
    while IFS= read -r variable; do
      case "$variable" in
        GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_COMMON_DIR|GIT_OBJECT_DIRECTORY|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_NAMESPACE|GIT_SHALLOW_FILE|GIT_REPLACE_REF_BASE|GIT_EXEC_PATH|GIT_CONFIG|GIT_CONFIG_*|GIT_TRACE*|GIT_REDIRECT_*|GIT_TEMPLATE_DIR|GIT_ATTR_*|GIT_ASKPASS)
          unset "$variable" ;;
      esac
    done < <(compgen -e)
    export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never
    # Preserve Git's SSH command/identity selection. OpenSSH force+false refuses
    # passphrase input without replacing a user's configured SSH command string.
    export GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false SSH_ASKPASS_REQUIRE=force
    export LC_ALL=C
    auth=()
    if [[ "$transport" == "$https_repository" && "$token_available" == true ]]; then
      export GIT_ASKPASS="$temporary/askpass.sh"
      auth=(-c credential.helper= -c credential.username=x-access-token -c credential.useHttpPath=true)
    fi
    command git -c core.hooksPath=/dev/null -c core.attributesFile=/dev/null \
      -c core.autocrlf=false -c protocol.ext.allow=never -c protocol.file.allow=never \
      -c http.followRedirects=false "${auth[@]}" "$@"
  )
}

version_greater() {
  local left=${1#codex/v} right=${2#codex/v}
  local left_major=${left%%.*} right_major=${right%%.*}
  local left_minor=0 right_minor=0
  [[ "$left" != *.* ]] || left_minor=${left#*.}
  [[ "$right" != *.* ]] || right_minor=${right#*.}
  if [[ ${#left_major} -ne ${#right_major} ]]; then [[ ${#left_major} -gt ${#right_major} ]]; return; fi
  if [[ "$left_major" != "$right_major" ]]; then [[ "$left_major" > "$right_major" ]]; return; fi
  if [[ ${#left_minor} -ne ${#right_minor} ]]; then [[ ${#left_minor} -gt ${#right_minor} ]]; return; fi
  if [[ "$left_minor" != "$right_minor" ]]; then [[ "$left_minor" > "$right_minor" ]]; return; fi
  [[ "$1" > "$2" ]]
}

select_head() {
  local heads=$1 sha ref extra candidate
  selected_branch='' selected_commit=''
  while IFS=$' \t' read -r sha ref extra; do
    [[ -z ${extra:-} && "$sha" =~ ^[0-9a-f]{40}$ && "$ref" == refs/heads/* ]] || continue
    candidate=${ref#refs/heads/}
    [[ "$candidate" =~ $branch_pattern ]] || continue
    [[ -z "$branch" || "$candidate" == "$branch" ]] || continue
    if [[ "$candidate" == "$selected_branch" && "$sha" != "$selected_commit" ]]; then
      fail 'Git returned conflicting revisions for the selected branch.'
    fi
    if [[ -z "$selected_branch" ]] || version_greater "$candidate" "$selected_branch"; then
      selected_branch=$candidate selected_commit=$sha
    fi
  done <<< "$heads"
  [[ -n "$selected_commit" ]]
}

transports=("$repository")
[[ -n "$repository" ]] || transports=("$https_repository" "$ssh_repository")
selected_branch='' selected_commit='' selected_repository=''
for transport in "${transports[@]}"; do
  if heads=$(git_run "$transport" ls-remote --heads "$transport" "refs/heads/${branch:-codex/v*}" 2>/dev/null) && select_head "$heads"; then
    selected_repository=$transport
    break
  fi
done
[[ -n "$selected_repository" ]] || fail 'Cannot read a supported Codex branch. This private repository requires an authorized Git credential helper, GITHUB_TOKEN/GH_TOKEN with repository access, or a configured GitHub SSH key. Git author name/email are not authentication. No tool installation was changed.'
unset heads

source_root="$temporary/source"
git_run "$selected_repository" init --quiet --template="$temporary/empty-template" "$source_root" >/dev/null 2>&1 || fail 'Could not prepare an isolated download directory.'
git_run "$selected_repository" -C "$source_root" fetch --quiet --depth=1 --no-tags "$selected_repository" "$selected_commit" >/dev/null 2>&1 || fail 'The selected revision could not be downloaded. Check repository access and rerun; no tool installation was changed.'
fetched=$(git_run "$selected_repository" -C "$source_root" rev-parse --verify 'FETCH_HEAD^{commit}' 2>/dev/null) || fail 'The download did not resolve to a commit.'
[[ "$fetched" == "$selected_commit" ]] || fail 'The downloaded revision differs from the selected branch revision.'

# Inspect Git objects before extraction. No checkout filters or hooks run.
git_run "$selected_repository" -C "$source_root" ls-tree -r -l -z --full-tree "$selected_commit" > "$temporary/tree" 2>/dev/null || fail 'The downloaded source tree could not be inspected.'
count=0 total=0
while IFS= read -r -d '' entry; do
  [[ "$entry" == *$'\t'* ]] || fail 'The downloaded source tree has invalid entries.'
  header=${entry%%$'\t'*} path=${entry#*$'\t'}
  read -r mode kind object bytes extra <<< "$header"
  [[ -z ${extra:-} && "$kind" == blob && "$object" =~ ^[0-9a-f]{40}$ && "$bytes" =~ ^[0-9]+$ ]] || fail 'The source contains unsupported Git objects or submodules.'
  [[ "$mode" == 100644 || "$mode" == 100755 ]] || fail 'The source contains links or unsupported file modes.'
  [[ -n "$path" && "$path" != /* && "$path" != *\\* && "$path" != *:* && "$path" != *//* && ! "$path" =~ [[:cntrl:]] ]] || fail 'The source contains an unsafe file path.'
  IFS=/ read -r -a components <<< "$path"
  for component in "${components[@]}"; do
    [[ -n "$component" && "$component" != . && "$component" != .. && "${component,,}" != .git && "$component" != *'.' && "$component" != *' ' ]] || fail 'The source contains an unsafe file path.'
  done
  [[ ${#bytes} -le 8 ]] || fail 'The source exceeds download size limits.'
  count=$((count+1))
  total=$((total+bytes))
  [[ $count -le 10000 && $bytes -le 16777216 && $total -le 100663296 ]] || fail 'The source exceeds download size limits.'
done < "$temporary/tree"
[[ $count -gt 0 ]] || fail 'The downloaded source tree is empty.'
git_run "$selected_repository" -C "$source_root" update-ref HEAD "$selected_commit" >/dev/null 2>&1 || fail 'Could not retain source provenance.'
git_run "$selected_repository" -C "$source_root" read-tree "$selected_commit" >/dev/null 2>&1 || fail 'Could not retain the source index.'
git_run "$selected_repository" -C "$source_root" archive --format=tar --output="$temporary/source.tar" "$selected_commit" >/dev/null 2>&1 || fail 'The source archive could not be produced.'
tar --extract --file "$temporary/source.tar" --directory "$source_root" --no-same-owner --no-same-permissions 2>/dev/null || fail 'The source archive could not be extracted.'

metadata="$source_root/.agents/skills/harness/scripts/harness_metadata.py"
[[ -f "$metadata" && -f "$source_root/install.sh" && -f "$source_root/harness.py" ]] || fail 'The selected branch does not contain the supported Codex command installer.'
version_pattern='^[[:space:]]*HARNESS_VERSION[[:space:]]*=[[:space:]]*"((0|[1-9][0-9]*)\.(0|[1-9][0-9]*))"[[:space:]]*$'
declared_version='' declarations=0
runtime_pattern='^[[:space:]]*RUNTIME[[:space:]]*=[[:space:]]*"codex"[[:space:]]*$'
runtime_declarations=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line=${line%$'\r'}
  if [[ "$line" =~ $version_pattern ]]; then
    declared_version=${BASH_REMATCH[1]}
    ((declarations+=1))
  fi
  if [[ "$line" =~ $runtime_pattern ]]; then ((runtime_declarations+=1)); fi
done < "$metadata"
expected_version=${selected_branch#codex/v}
[[ "$expected_version" == *.* ]] || expected_version+=.0
[[ $declarations -eq 1 && "$declared_version" == "$expected_version" ]] || fail 'The downloaded source version does not match its selected branch.'
[[ $runtime_declarations -eq 1 ]] || fail 'The downloaded source does not declare the Codex runtime.'

printf 'Installing Harness for Codex %s from %s (%s).\n' "$declared_version" "$selected_branch" "$selected_commit"
# No --branch means keep following the numeric latest Codex channel after setup.
install_args=("--repository" "$selected_repository")
[[ -z "$branch" ]] || install_args+=("--branch" "$branch")
install_args+=("${forward[@]}")
bash "$source_root/install.sh" "${install_args[@]}"
