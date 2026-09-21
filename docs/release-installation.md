### Linux installation

```bash
curl -fsSL https://github.com/sholee-pt/Harness-Codex/releases/download/v{version}/install_harness_codex.sh | sh
harness-codex --version
# Existing tool installation:
harness-codex update
# Review existing project artifacts when configuration needs updating:
harness-codex config --project /path/to/project
```

The installer prepares the isolated tool environment and registers PATH. Open a new shell with the installation prompt, or run `source ~/.bashrc` in the current shell. Install and sign in to Codex separately. Start project work with `codex`; use `codex resume` for an existing conversation.

The source installer supports Linux x86_64 and aarch64; the native Auto package is published for x86_64. On aarch64, use `init --no-codex-integration` with a separately installed Codex. Windows releases remain paused.

### Release assets and verification

| Asset | Purpose |
| --- | --- |
| `install_harness_codex.sh` | Linux downloader and isolated tool setup |
| `harness-codex-{version}-linux.tar.gz` | Generator, CLI and source installer |
| `harness-codex-ui-{version}-linux-x86_64.tar.gz` | Native Codex with the Auto extension and required helper resources |
| `SHA256SUMS` | Checksums of the downloadable assets |
| `build.json` | Exact source commit, platforms and native package fingerprints |

Linux publication requires installation, upgrade and native TUI/extension checks. These establish tested behavior, not model quality or token savings. The installer verifies the archive automatically. For manually downloaded assets, use `sha256sum --check SHA256SUMS` in the download directory.

Use `harness-codex uninstall` to review tool removal and confirm with `yes`. Project harnesses and native conversation history are preserved.
