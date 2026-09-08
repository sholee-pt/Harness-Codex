#!/bin/sh
# Public, version-bound bootstrap. This entire file also works through `| sh`.
set -eu
VERSION=9.8
fail() { printf 'Harness for Codex installer: %s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' 'Usage: sh install_harness_codex.sh [OPTIONS]' \
    'Installs harness-codex and its dedicated Python environment without sudo.' \
    '  --bin-dir PATH          Command directory (default: ~/.local/bin)' \
    '  --data-dir PATH         Managed Codex tool storage' \
    '  --auto-update POLICY    compatible, check, or off' \
    '  --no-modify-path        Do not register PATH in ~/.bashrc' \
    '  --help                  Offline help' \
    'Linux x86_64/aarch64. Requires curl, Bash, tar and sha256sum.' \
    'Existing Conda is reused; otherwise a checksum-pinned Miniforge is installed.'
}
validate_options() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --no-modify-path) shift ;;
      --bin-dir|--data-dir|--auto-update|--repository|--branch|--agent|--runtime)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
        key=$1; value=$2; shift 2
        case "$key" in
          --agent|--runtime) [ "$value" = codex ] || fail 'This installer is for Codex only; Claude is not implemented.' ;;
          --branch) [ "$value" = "codex/v$VERSION" ] || fail "This installer is pinned to codex/v$VERSION." ;;
          --auto-update) case "$value" in compatible|check|off) ;; *) fail 'Invalid automatic update policy.' ;; esac ;;
        esac ;;
      *) fail "Unknown option: $1. Use --help." ;;
    esac
  done
}
main() {
  for argument in "$@"; do
    case "$argument" in --help|-h) usage; return ;; esac
  done
  validate_options "$@"
  [ "$(uname -s)" = Linux ] || fail 'This installer supports Linux only.'
  for prerequisite in curl bash tar sha256sum mktemp rm awk; do
    command -v "$prerequisite" >/dev/null 2>&1 || fail "Required command missing: $prerequisite"
  done
  temporary=$(mktemp -d "${TMPDIR:-/tmp}/harness-codex-install.XXXXXXXX")
  trap 'rm -rf -- "$temporary"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  base="https://github.com/sholee-pt/Harness/releases/download/codex-v$VERSION"
  archive="harness-codex-$VERSION-linux.tar.gz"
  printf 'Downloading Harness for Codex %s...\n' "$VERSION"
  for name in "$archive" SHA256SUMS; do
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      --connect-timeout 15 --max-time 300 --retry 2 "$base/$name" -o "$temporary/$name" </dev/null \
      || fail 'Release download failed. The public one-line installer requires public release access; private repositories still need authentication.'
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
