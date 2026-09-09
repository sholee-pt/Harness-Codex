# Development and stable versions

Development releases use `vX.Y.Z-beta`. X marks a major change, Y a feature addition
or compatible feature revision, and Z a bug fix, chore or refactoring. Incrementing
Y resets Z; incrementing X resets Y and Z. A release containing both a feature and
a bug fix uses the feature increment.

Earlier two-component labels were development versions. Display `v8.7` as
`v0.8.7-beta`, and the immediately preceding `v9.11` as `v0.9.11-beta`. The bounded
maintenance feature therefore starts `v0.10.0-beta`, not `v0.9.12-beta`. Historical
changes were not retroactively classified according to SemVer: this is a display
mapping. Existing commits, historical tags, installation receipts, evaluation
records and generated manifest hashes are not rewritten to change their labels.

New branches and tags are `codex/v0.10.0-beta` and `codex-v0.10.0-beta`. GitHub
releases are explicitly marked prerelease. Prereleases are not GitHub's stable
`releases/latest`; use the pinned installation URL in README. The current Claude
branch is preserved independently.

Once the repository is made public and a stable release is explicitly published,
stable versioning starts at `v1.0.0`. Changing GitHub visibility alone does not build
or publish a release. Major changes include incompatible generation/ownership
contracts; feature and patch changes must preserve documented compatibility.

## One-time migration from legacy installations

The previous updater recognizes only branches such as `codex/v9.11`; it cannot
discover `codex/v0.10.0-beta`. Run the new installer once with existing-installation
mode `reuse`. This keeps owned preferences, recognizes the earlier installation and
preserves project harnesses. Thereafter `harness-codex update` understands beta and
stable release names. A legacy pinned branch is retired during this one-time
`reuse` migration so the installation can follow new releases; the installer reports
that change. Repository transport and automatic-update preference are retained.
Thereafter it compares normalized beta and
stable versions and refuses genuine downgrades. The tool update policy follows the
normalized major component; project artifact compatibility is checked separately.

From a current authenticated checkout:

```sh
bash installer/install.sh --existing reuse
```

```powershell
./installer/install.ps1 -Existing reuse
```

To adopt new project-generation guidance, run `harness-codex config` in the project.
It refreshes only an owned, unchanged generator and reviews the existing harness.
There is no automatic reset, disk-wide project scan, or project Git operation.
