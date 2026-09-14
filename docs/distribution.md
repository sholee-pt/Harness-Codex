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

`build/release_notes.py` extracts the selected version section from root `CHANGELOG.md`. CI publishes that text as the GitHub release body after Linux verification. The release body is a copy at publication time, not a live Markdown-file link. There is no root `RELEASE_NOTES.md`. Historical versions are linked within the changelog even when old branches no longer exist.

Verification includes ownership and source contracts, generation/apply fixtures, session argument transport, installation upgrades from the immediately preceding release, checksums, isolated installers and uninstall safeguards. Transport fixtures use the exact built Harness assets; external Miniforge/Conda setup is tested separately against actual upstream downloads. A successful file/CLI test does not establish live agent discovery, model quality or token savings.

Branch pushes run verification. To publish through Actions, dispatch the current branch workflow with `publish` enabled; the Linux management checks, native build and full TUI/extension suite must pass first. Tag creation does not start a duplicate verification/publication run. Existing published assets are never overwritten by this workflow. Windows executables, ZIPs and PowerShell downloaders are not published while Windows validation is paused.

Native tests use the upstream `ci-test` compiler profile and its `0.0.0` development-version fixture, which the original UI snapshots assume. The test runner restores `Cargo.toml` and `Cargo.lock` byte-for-byte on both success and failure before a release build can start. External dependency versions, upstream assertions and snapshots remain unchanged; the reviewed Auto menu snapshot is supplied separately. The shipped binary is built in release mode with the actual pinned Codex version `0.154.0`. Test snapshots cannot be accepted automatically in CI.
