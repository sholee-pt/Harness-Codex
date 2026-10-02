# Contributing

Changes should keep Harness small, runtime-native, and safe to rerun. See the license before redistributing modifications.

## Branches

- Harness for Codex development branches use `vX.Y.Z-beta`, with tags such as `v0.12.0-beta`. These are Harness versions, not Codex product versions.
- This repository contains the Codex edition only.
- X marks major or large-scale changes; Y covers minor features, improvements, refactoring and optimization; Z covers bug fixes. Explanatory documentation-only changes do not increment the version.
- Start a new version branch from the latest verified release branch. See [versioning](docs/versioning.md) for the full policy and release reset.

## Commit messages

Use one of these prefixes:

- `[Feat]` for user-visible capability
- `[Fix]` for incorrect behavior
- `[Doc]` for explanatory documentation-only changes, without a version bump
- `[Refactor]` for structural changes without intended behavior changes
- `[Test]` for test changes
- `[Chore]` for maintenance

Keep each commit focused and use an imperative, descriptive subject.

The `[Doc]` rule applies to repository explanations such as README, contribution rules and release documentation. Instructions, templates or contracts that directly affect harness generation or execution are behavioral inputs, even in Markdown; classify their changes as features, fixes or refactoring as appropriate. For mixed commits, classify the behavioral change and apply its version increment.

## Quality requirements

- Preserve existing user content during generation and updates.
- Keep Codex output compatible with the official project agent and skill locations.
- Add or update tests for deterministic helper behavior.
- Do not introduce model, tool, or deployment assumptions that cannot be verified at runtime.

## Repository layout

| Location | Responsibility |
| --- | --- |
| `installer/install_harness_codex.sh` / `.ps1` | Download and verify release assets; published as standalone Linux/Windows installers |
| `installer/install.sh` / `.ps1` | Prepare Conda and install from a checkout or verified archive |
| `harness.py` / `install.py` | Small CLI/project-installer entry points whose root paths remain compatible with existing installations |
| `harness_cli/project_installer.py` | Project-local generator installation, ownership, rollback and source-bound installer loading |
| `harness_cli/paths.py` | Low-level CLI path checks shared by distribution, PATH registration and release builds |
| `harness_cli/` | CLI commands, managed tool storage, updates, lifecycle and environment handling |
| `build/build_release.py` | Developer/CI command and build orchestration |
| `build/source.py` | Release input collection, source identity and completeness checks |
| `build/artifacts.py` | Deterministic Linux/Windows archives, installers and checksum reports |
| `.agents/skills/harness/` | Generator instructions, contracts, helpers and templates |
| `test/test_*.py` | Unit/regression tests discovered by unittest |
| `test/integration/` | Explicit release, installation, upgrade and parser-oracle checks |
| `test/fixtures/` | Shared deterministic projects and expected results |

The independent Git-download bootstrap `install_harness.sh` was retired after v9.8 publication. Use a source clone followed by `bash installer/install.sh` on Linux or `./installer/install.ps1` on Windows. Release downloaders and source installers share the same installation implementation.

The entire `build/` package is excluded from installed runtime payloads. Source completeness and path checks shared with installation remain in `harness_cli/`; build code reuses them so installation and build validation cannot diverge.

The builder maps the two source installers back to `install.sh` and `install.ps1` at the archive root. Release download URLs and extracted-archive commands are unchanged. Download-only bootstraps are separate release assets and are not duplicated inside runtime archives. Historical optional installer names remain accepted in `harness_cli/distribution.py` so existing managed installation receipts still validate.

Previous-version tests are compatibility requirements, not disposable release logs. Artifact compatibility cases live in `test_apply_compatibility.py`; the integration checks also execute immutable old source revisions. Removing a feature may remove tests exclusive to that feature, but moving or combining suites must preserve all other scenarios.

CLI source validation checks both version-specific requirements and declared first-party module imports without executing candidate code. This preserves complete historical layouts while rejecting missing modules introduced by refactors. Project and lifecycle commands share the installer loader, which binds to the selected source directory and does not write bytecode into immutable releases. Project-installer ownership/rollback checks remain separate from CLI storage rules.

## Running checks

Use the dedicated `harness` Conda environment for every Python command:

```bash
conda run -n harness python install.py --root TARGET_PROJECT --dry-run
conda run -n harness python -B -m unittest discover -s test -v
conda run -n harness python build/build_release.py --output /tmp/harness-dist
```

Build output must be outside the repository. Only local development builds may use `--allow-dirty`.

Integration checks currently run explicitly in CI on Linux. Windows builds and platform validation are paused until separately requested. For example:

```bash
conda run -n harness python test/integration/prepare_release_baselines.py --output /tmp/harness-baselines
conda run -n harness python test/integration/verify_cli_upgrade.py --baseline /tmp/harness-baselines/v0310 --output /tmp/cli-upgrade.json
conda run -n harness python test/integration/verify_release_upgrade.py --baseline /tmp/harness-baselines/v0310 --output /tmp/project-upgrade.json
```

Release comparison runs only against the immediately preceding version baseline (v0.31.0-beta). CI does not recreate the entire historical version matrix. Functional regression tests still check supported contracts and failure cases. Add an older source comparison only for a concrete compatibility defect that requires it.

Parser differential checks require the pinned optional `test/requirements-validation.txt`. Cold installer checks download Miniforge and create an isolated environment; the Windows registry/cold check is restricted to disposable CI runners. These are distinct from unit tests and must not run implicitly during unittest discovery.

Release bodies are extracted from the current version section with `build/release_notes.py`; see [distribution](docs/distribution.md). Source installer options and ownership are described in [installation](docs/installation.md).
