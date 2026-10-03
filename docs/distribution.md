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

The publisher requires exactly the four Linux assets listed above. Before any GitHub request, it checks bounded regular files, both asset digests against the checksum manifest and build report, archive paths and limits, and the complete payload against the selected clean checkout's immutable source. It uploads a private copy of those verified bytes and preserves existing version tags. Source downloads and provenance checks archive only declared distribution/runtime paths, so unrelated documentation and fixtures do not consume runtime archive limits.

Repeated installed-status checks still re-read and hash every managed file, receipt and launcher. Only successful syntax/import analysis of an identical verified source hash is reused in a bounded process-local cache; local changes or a different source hash receive the existing ownership checks and fresh analysis.

After confirming successful publication and the Linux installer asset, update the README's **Latest release** label and installation URL to that version in a `[Doc]` commit without a version bump. Keep this block pinned to the published release while the development branch advances. Create each release with its version tag from the start; retain older version tags, assets and their version-specific installation instructions when publishing the next release. Do not rename or move version tags to track the latest release.

Checks and releases are currently on a manual hold: branch pushes do not start Actions. When authorized, dispatch the current branch workflow with `publish` disabled for checks or enabled for release. Publication requires generation/apply, installer, ownership, uninstall, immediate-previous-version upgrade checks and the official Linux terminal/production-adapter gate. The latter resolves the latest official stable package at run time, verifies its digest, exercises Auto with a synthetic local model provider, and checks that binary bytes remain unchanged. It requires the Auto menu and actual selected model/reasoning in the footer and provider requests, plus native resume/fork picker transitions without replaying inference. Failure blocks publication. No Rust compilation is part of this Linux workflow.

This establishes tested terminal and protocol behavior, not paid account compatibility, model quality, token savings or all future Codex APIs. Runtime capabilities are checked at launch, with an explicit native-mode fallback. The retained `build/native_ui` code and its tests support legacy package ownership and potential Windows maintenance; they are not the current Linux release path. Windows releases remain paused until separately authorized.

Interactive prelaunch checks display their progress. Native fallback guidance explicitly identifies both unavailable features—Harness Auto and `/harness/` management—and supplies terminal commands for the selected project. These messages do not change Codex arguments, settings or permissions, and do not add checks to help, automation or disabled update channels.

Workflows publish `Harness / verification` and `Harness / release` commit statuses against their exact `GITHUB_SHA`. A release alone does not create a commit checkmark. Cancelled, skipped or failed required jobs cannot produce a successful release status. After dispatch, provide the Actions link and stop; the repository owner checks progress. Do not poll, watch or schedule monitoring without a new request.
