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

Official Codex is downloaded independently during integration setup and confirmed updates; no Codex build is required. The terminal release gate runs on Linux x86_64. Linux aarch64 package resolution is supported but not covered by that gate. Windows releases remain paused. For migration from the old patched integration, use this installer with `--existing reuse`, then run `config` once.

### Release assets and verification

| Asset | Purpose |
| --- | --- |
| `install_harness_codex.sh` | Linux downloader and isolated tool setup |
| `harness-codex-{version}-linux.tar.gz` | Generator, CLI and source installer |
| `SHA256SUMS` | Checksums of the downloadable assets |
| `build.json` | Exact Harness source commit and platforms |

Linux publication requires installation, upgrade and official TUI/production-adapter checks. These establish tested behavior with synthetic model responses, not paid account compatibility, model quality or token savings. The installer verifies the archive automatically. For manually downloaded assets, use `sha256sum --check SHA256SUMS` in the download directory. Interactive `codex` launches offer updates for published Codex and Harness releases before opening a conversation; downloads require your selection.

Use `harness-codex uninstall` to review tool removal and confirm with Enter, `y` or `yes`; decline with `n` or `no`. Project harnesses and native conversation history are preserved.
