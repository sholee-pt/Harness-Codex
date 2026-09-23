# Release assets and verification

Each [GitHub Release](https://github.com/sholee-pt/Harness-Codex/releases) contains its installation instructions and changes directly in the release body.

| Asset | Purpose |
| --- | --- |
| `install_harness_codex.sh` | One-command Linux downloader and checksum verifier |
| `harness-codex-VERSION-linux.tar.gz` | Linux source distribution, including `install.sh` |
| `harness-codex-ui-VERSION-linux-x86_64.tar.gz` | Pinned native Codex with Auto, official helper resources, fingerprints and upstream license/notice; installed by init/config |
| `SHA256SUMS` | SHA-256 digests of the release assets |
| `build.json` | Source commit and reproducible-build metadata |

GitHub's automatically generated source archives are repository snapshots. Use the platform release archive or installer for tool installation. Verify downloaded files on Linux with `sha256sum --check SHA256SUMS`; on Windows compare `Get-FileHash -Algorithm SHA256 PATH` with the matching entry. The bootstrap verifies its archive automatically over HTTPS.

## Maintainers

Build with `conda run -n harness python build/build_release.py --output PATH` from clean committed source. The default emits Linux assets only and records `platforms: ["linux"]` in `build.json`. Attachment requires the declared native package, its exact source commit and valid fingerprints. Missing, duplicate or undeclared platform packages block publication. `--platform both` is retained for future Windows verification; CI does not use it while Windows work is paused. Local inspection may use `--allow-dirty`; such artifacts do not claim a release commit.

`CHANGELOG.md` contains version-specific changes only. `build/release_notes.py` combines the selected version section with `docs/release-installation.md`, replacing `{version}` with the release version. CI publishes the combined text as the GitHub release body after Linux verification. The release body is a copy at publication time, not a live Markdown-file link. There is no root `RELEASE_NOTES.md`. Historical versions are linked within the changelog even when old branches no longer exist. Version policy and historical label conventions are documented in [versioning](versioning.md).

Verification includes ownership and source contracts, generation/apply fixtures, session argument transport, installation upgrades from the immediately preceding release, checksums, isolated installers and uninstall safeguards. Transport fixtures use the exact built Harness assets; external Miniforge/Conda setup is tested separately against actual upstream downloads. A successful file/CLI test does not establish live agent discovery, model quality or token savings.

Branch pushes run verification. To publish through Actions, dispatch the current branch workflow with `publish` enabled; the Linux management checks, native build and full TUI/extension suite must pass first. Tag creation does not start a duplicate verification/publication run. Existing published assets are never overwritten by this workflow. Windows executables, ZIPs and PowerShell downloaders are not published while Windows validation is paused.

Verification and release runs also publish `Harness / verification` and `Harness / release` commit statuses against their exact `GITHUB_SHA`. A release, a successful check run and a legacy commit status are separate GitHub objects; publishing a release alone does not create a checkmark. Missing legacy statuses do not mean existing successful GitHub Checks failed. Cancelled, missing or skipped required release jobs cannot produce a successful release status. The reusable native workflow has no push trigger, preventing a second native compilation alongside an explicitly requested release.

After dispatch, provide the Actions link and stop. The repository owner checks progress directly; do not poll, watch or schedule monitoring without a new request.

Native tests use the upstream `ci-test` compiler profile and its `0.0.0` development-version fixture, which the original UI snapshots assume. The test runner restores `Cargo.toml` and `Cargo.lock` byte-for-byte on both success and failure before a release build can start. External dependency versions, upstream assertions and snapshots remain unchanged; the reviewed Auto menu snapshot is supplied separately. The shipped binary is built in release mode with the actual pinned Codex version `0.154.0`. Test snapshots cannot be accepted automatically in CI.

Cargo reconciles the test fixture lock offline, including implicit workspace members such as nested test-support crates. The external package version/source/checksum set must remain identical. A real `cargo metadata --locked` preflight checks this graph before compilation; the full nextest run also retains `--locked`. Failed preflight or dependency drift blocks both compilation and publication.

Linux native CI removes fixed, unused Android/.NET/Haskell SDK directories only on disposable GitHub-hosted runners and requires 25 GiB free before compiling. Clippy and the full TUI suite share an isolated `ci-test` output directory with incremental compilation and debug information disabled. Available JUnit results are copied out before deleting that output, including after a failed test step. Only then is the separate release cache restored; release compilation requires 15 GiB free afterward. Disk checks and cleanup do not skip tests or convert a failed test result into success. These thresholds are build capacity checks, not end-user installation requirements.

Native Cargo jobs and nextest test threads are each limited to one. Expensive build commands run at lower scheduling priority and log memory, swap, disk and available kernel memory-pressure events every minute. On hosted runners with less than 12 GiB RAM, preparation supplements existing swap up to 8 GiB without consuming the 25 GiB test-build disk reserve. Only disposable GitHub-hosted Linux runners may allocate this buffer; unrelated files are never overwritten and allocation or activation errors fail the job. Commands retain their original exit status and test scope.

The v0.20.0-beta release run lost communication with its runner during TUI compilation and exited with SIGTERM (143), before test results were available. That evidence establishes runner loss, not an out-of-memory diagnosis. Resource preparation reduces build pressure and the additional logs help distinguish resource exhaustion from another infrastructure failure on a retry; local regression tests alone do not prove native release success.

Swap allocation includes page alignment, the reserved header page and mkswap's minimum area size; the 8 GiB target refers to usable swap, while the disk reserve includes the full allocation. The new file is root-owned with mode 0600 before activation. Diagnostics report capacity before and after preparation. If setup fails before the upstream clone, patch collection reports unavailable evidence without accessing a nonexistent directory or creating an empty patch artifact. The original setup failure still blocks publication.
