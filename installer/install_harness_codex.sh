#!/bin/sh
# Public, version-bound bootstrap. This entire file also works through `| sh`.
set -eu
VERSION=0.12.0-beta
fail() { printf 'Harness for Codex installer: %s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' 'Usage: sh install_harness_codex.sh [OPTIONS]' \
    'Installs harness-codex and its dedicated Python environment without sudo.' \
    '  --bin-dir PATH          Command directory (default: ~/.local/bin)' \
    '  --data-dir PATH         Managed Codex tool storage' \
    '  --auto-update POLICY    compatible, check, or off' \
    '  --existing MODE         ask (default), reuse, or reset Harness settings' \
    '  --activate MODE         ask (default), shell, or skip opening a ready Bash' \
    '  --no-modify-path        Do not register PATH in ~/.bashrc' \
    '  --no-codex-integration  Install only the Harness management tool' \
    '  --help                  Offline help' \
    'Linux x86_64/aarch64. Requires curl, Bash, tar and sha256sum.' \
    'Existing Conda is reused; otherwise a checksum-pinned Miniforge is installed.'
}
validate_options() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --no-modify-path|--no-codex-integration) shift ;;
      --bin-dir|--data-dir|--auto-update|--existing|--activate|--repository|--branch|--agent|--runtime)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
        key=$1; value=$2; shift 2
        case "$key" in
          --agent|--runtime) [ "$value" = codex ] || fail 'This installer is for Codex only; Claude is not implemented.' ;;
          --branch) [ "$value" = "v$VERSION" ] || fail "This installer is pinned to v$VERSION." ;;
          --auto-update) case "$value" in compatible|check|off) ;; *) fail 'Invalid automatic update policy.' ;; esac ;;
          --existing) case "$value" in ask|reuse|reset) ;; *) fail 'Invalid existing-installation choice.' ;; esac ;;
          --activate) case "$value" in ask|shell|skip) ;; *) fail 'Invalid activation choice.' ;; esac ;;
          --repository) case "${value%.git}" in
            https://github.com/sholee-pt/Harness|https://github.com/sholee-pt/Harness-Codex|git@github.com:sholee-pt/Harness|git@github.com:sholee-pt/Harness-Codex|ssh://git@github.com/sholee-pt/Harness|ssh://git@github.com/sholee-pt/Harness-Codex) ;;
            *) fail 'Select the Harness-Codex repository.' ;; esac ;;
          --data-dir) data_directory=$value ;;
          --bin-dir) bin_directory=$value ;;
        esac ;;
      *) fail "Unknown option: $1. Use --help." ;;
    esac
  done
}
preflight_path() {
  path=$1
  printf '%s\n' "$path" | awk 'NR > 1 || /\r/ {exit 1}' || fail 'Installation paths must contain no line breaks.'
  case "$path" in '~') path=$HOME ;; '~/'*) path=$HOME/${path#\~/} ;; esac
  while [ "$path" != / ]; do
    case "$path" in */.) path=${path%/.} ;; */) path=${path%/} ;; *) break ;; esac
    [ -n "$path" ] || path=/
  done
  [ ! -L "$path" ] || fail "Installation root is a symlink; preserved: $path"
  [ ! -e "$path" ] || [ -d "$path" ] || fail "Installation path is not a directory; preserved: $path"
  resolved=$(realpath -m -- "$path") || fail 'Cannot resolve installation path.'
  for candidate in "$1" "$path" "$resolved"; do
    printf '%s\n' "$candidate" | awk -F/ 'NR > 1 || /\r/ {exit 1} {for (i=1;i<=NF;i++) {part=tolower($i); sub(/[ .]+$/, "", part); if (part == ".git") exit 1}}' \
      || fail 'Installation paths must remain outside Git metadata and contain no line breaks.'
  done
  candidate=$resolved
  while [ "$candidate" != / ]; do
    [ ! -e "$candidate" ] || [ -d "$candidate" ] || fail "Installation path is not a directory; preserved: $candidate"
    candidate=$(dirname -- "$candidate")
  done
}
main() {
  for argument in "$@"; do
    case "$argument" in --help|-h) usage; return ;; esac
  done
  data_directory=${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex
  bin_directory=$HOME/.local/bin
  validate_options "$@"
  [ "$(uname -s)" = Linux ] || fail 'This installer supports Linux only.'
  for prerequisite in curl bash tar sha256sum mktemp rm awk realpath dirname; do
    command -v "$prerequisite" >/dev/null 2>&1 || fail "Required command missing: $prerequisite"
  done
  preflight_path "$data_directory"
  case "$data_directory" in '~') data_directory=$HOME ;; '~/'*) data_directory=$HOME/${data_directory#\~/} ;; esac
  data_directory=$(realpath -m -- "$data_directory") || fail 'Cannot resolve installation path.'
  preflight_path "$data_directory-runtime"
  preflight_path "$bin_directory"
  temporary=$(mktemp -d "${TMPDIR:-/tmp}/harness-codex-install.XXXXXXXX")
  trap 'rm -rf -- "$temporary"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  base="https://github.com/sholee-pt/Harness-Codex/releases/download/v$VERSION"
  archive="harness-codex-$VERSION-linux.tar.gz"
  printf 'Downloading Harness for Codex %s...\n' "$VERSION"
  for name in "$archive" SHA256SUMS; do
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      --connect-timeout 15 --max-time 300 --retry 2 "$base/$name" -o "$temporary/$name" </dev/null \
      || fail 'Release download failed. Check network access and the release URL.'
  done
  printf 'Verifying checksum and extracting the release...\n'
  expected=$(awk -v name="$archive" '$2 == name {print $1}' "$temporary/SHA256SUMS")
  [ "${#expected}" -eq 64 ] || fail 'Missing or ambiguous archive checksum.'
  case "$expected" in *[!0-9a-f]*) fail 'Invalid archive checksum.' ;; esac
  actual=$(sha256sum "$temporary/$archive")
  [ "${actual%% *}" = "$expected" ] || fail 'Archive checksum mismatch; nothing was installed.'
  tar -tzf "$temporary/$archive" > "$temporary/members"
  while IFS= read -r member; do
    case "$member" in "harness-codex-$VERSION/"*) ;; *) fail 'Unexpected archive root.' ;; esac
    case "/$member/" in *'/../'*|*'/./'*) fail 'Unsafe archive path.' ;; esac
  done < "$temporary/members"
  tar -tvzf "$temporary/$archive" > "$temporary/types"
  awk 'substr($0, 1, 1) != "-" {exit 1}' "$temporary/types" || fail 'Only regular archive files are accepted.'
  tar -xzf "$temporary/$archive" --no-same-owner --no-same-permissions -C "$temporary"
  bash "$temporary/harness-codex-$VERSION/install.sh" "$@" </dev/null
}
main "$@"
