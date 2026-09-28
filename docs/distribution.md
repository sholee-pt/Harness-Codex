# Release assets and verification

Each [GitHub Release](https://github.com/sholee-pt/Harness-Codex/releases) contains installation instructions and version changes directly in its body.

| Asset | Purpose |
| --- | --- |
| `install_harness_codex.sh` | One-command Linux downloader and checksum verifier |
| `harness-codex-VERSION-linux.tar.gz` | Generator, management CLI, Auto adapter and source installer |
| `SHA256SUMS` | SHA-256 digests of the release assets |
| `build.json` | Exact Harness source commit and build metadata |

Official Codex packages are fetched separately from `openai/codex` during integration setup and confirmed updates. They are neither rebuilt nor repackaged as Harness-versioned UI assets. Source snapshots generated automatically by GitHub are not the release installers.

## Maintainers

Build with `conda run -n harness python build/build_release.py --output PATH` from clean committed source. The default emits Linux assets only. Local inspection may use `--allow-dirty`; these artifacts cannot claim an immutable source commit. `build/release_notes.py` combines the current changelog section with `docs/release-installation.md`. Published release text is a copy, not a live Markdown-file link.

Branch pushes run management verification. Dispatch the current branch workflow with `publish` enabled for release. Publication requires generation/apply, installer, ownership, uninstall, immediate-previous-version upgrade checks and the official Linux terminal/production-adapter gate. The latter resolves the latest official stable package at run time, verifies its digest, exercises Auto with a synthetic local model provider, and checks that binary bytes remain unchanged. It requires the Auto menu and actual selected model/reasoning in the footer and provider requests. Failure blocks publication. No Rust compilation is part of this Linux workflow.

This establishes tested terminal and protocol behavior, not paid account compatibility, model quality, token savings or all future Codex APIs. Runtime capabilities are checked at launch, with an explicit native-mode fallback. The retained `build/native_ui` code and its tests support legacy package ownership and potential Windows maintenance; they are not the current Linux release path. Windows releases remain paused until separately authorized.

Workflows publish `Harness / verification` and `Harness / release` commit statuses against their exact `GITHUB_SHA`. A release alone does not create a commit checkmark. Cancelled, skipped or failed required jobs cannot produce a successful release status. After dispatch, provide the Actions link and stop; the repository owner checks progress. Do not poll, watch or schedule monitoring without a new request.
