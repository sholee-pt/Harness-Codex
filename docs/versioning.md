# Development and stable versions

Development releases use `vX.Y.Z-beta`.

| Change | Version increment | Commit prefix examples |
| --- | --- | --- |
| Major or large-scale change | X; reset Y and Z | `[Feat]`, `[Refactor]` |
| Minor feature, improvement, refactoring or optimization | Y; reset Z | `[Feat]`, `[Refactor]`, `[Chore]` |
| Bug fix | Z | `[Fix]` |
| Explanatory documentation with no effect on harness generation or execution | None | `[Doc]` |

Choose the increment by the change's effect. Refactoring and optimization use Y,
not Z. A release containing both a minor feature and a bug fix uses Y; a major
change takes precedence over both. Test and maintenance changes follow the same
effect-based rule rather than automatically using the bug-fix increment.

The documentation exception covers repository explanations, contribution rules
and release documentation. Generator instructions, templates and contracts are
behavioral inputs, even in Markdown. Changes to those inputs are classified by
their effect and are not automatically `[Doc]` changes. Mixed commits follow the
behavioral change's classification. An explanatory documentation-only commit
stays on the current version branch and keeps the existing version metadata.

## Release starting point and historical labels

Earlier two-component labels were development versions. Display `v8.7` as
`v0.8.7-beta`, and the immediately preceding `v9.11` as `v0.9.11-beta`. The bounded
maintenance feature therefore starts `v0.10.0-beta`, not `v0.9.12-beta`. Historical
changes were not retroactively classified according to SemVer: this is a display
mapping. Existing commits, installation receipts, evaluation records and generated
manifest hashes are not rewritten to change their labels.

The release and tag history is reset at `v0.10.0-beta`: all previous releases and
tags are removed, and `codex-v0.10.0-beta` is published from the commit containing
the clarified documentation policy. This is an explicitly authorized one-time
reset, not a requirement to recreate releases for later `[Doc]` commits. Historical
changelog entries remain as an archive; their old download URLs are no longer
supported. Use the current README installation links.

From `v0.11.0-beta`, the repository is `sholee-pt/Harness-Codex`. New branches and tags use `vX.Y.Z-beta`, without `codex/` or `codex-`. This repository contains only the Codex edition; the Claude branch is removed. The latest verified branch is the default. GitHub releases are marked prerelease, so installation uses the pinned README URL rather than the stable `releases/latest` endpoint.

Once the repository is made public and a stable release is explicitly published,
stable versioning starts at `v1.0.0`. Changing GitHub visibility alone does not build
or publish a release. Major changes include incompatible generation/ownership
contracts; feature and patch changes must preserve documented compatibility.

## One-time migration from legacy installations

The 0.10.0-beta updater recognizes only `codex/v*` branches and cannot discover the new unprefixed release branches. Run the current installer once with `reuse`. It preserves project harnesses and the automatic-update preference, maps the old repository address to Harness-Codex while preserving HTTPS/SSH transport, and retires an obsolete `codex/` branch pin. The installer reports this change. Immutable old receipts and the tool ownership identity remain readable. Subsequent updates understand both legacy receipt versions and current branch names; downgrade checks and project artifact compatibility remain separate.

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
