# Contributing

Harness is maintained as a private personal project. Changes should keep the generator small, runtime-native, and safe to rerun.

## Branches

- Harness for Codex releases use `codex/vN` or `codex/vN.M`; these are Harness versions, not Codex product versions.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Release and generator versions use two components (`N.M`). A branch named `codex/vN` is the preserved `.0` major release.
- Breaking changes start the next version branch from the latest branch for the same runtime.

## Commit messages

Use one of these prefixes after the initial version commit:

- `[Feat]` for user-visible capability
- `[Fix]` for incorrect behavior
- `[Docs]` for documentation-only changes
- `[Refactor]` for structural changes without intended behavior changes
- `[Test]` for test changes
- `[Chore]` for maintenance

Keep each commit focused and use an imperative, descriptive subject.

## Quality requirements

- Preserve existing user content during generation and updates.
- Keep Codex output compatible with the official project agent and skill locations.
- Add or update tests for deterministic helper behavior.
- Do not introduce model, tool, or deployment assumptions that cannot be verified at runtime.

## Repository layout

| Location | Responsibility |
| --- | --- |
| `installers/install_harness_codex.sh` / `.ps1` | Download and verify release assets; published as standalone Linux/Windows installers |
| `installers/install.sh` / `.ps1` | Prepare Conda and install from a checkout or verified archive |
| `harness.py` / `install.py` | Small CLI/project-installer entry points whose root paths remain compatible with existing installations |
| `harness_cli/project_installer.py` | Project-local generator installation, ownership, rollback and source-bound installer loading |
| `harness_cli/paths.py` | Low-level CLI path checks shared by distribution, PATH registration and release builds |
| `harness_cli/` | CLI commands, managed tool storage, updates, lifecycle and environment handling |
| `tools/build_release.py` | Developer/CI build tooling; excluded from installed runtime payloads |
| `.agents/skills/harness/` | Generator instructions, contracts, helpers and templates |
| `tests/test_*.py` | Unit/regression tests discovered by unittest |
| `tests/integration/` | Explicit release, installation, upgrade and parser-oracle checks |
| `tests/fixtures/` | Shared deterministic projects and expected results |

The independent Git-download bootstrap `install_harness.sh` was retired after v9.8 publication. Use an authenticated clone followed by `bash installers/install.sh` on Linux or `./installers/install.ps1` on Windows. GitHub authentication and branch updates remain in the installed CLI; ordinary Git handles initial private source access.

The builder maps the two source installers back to `install.sh` and `install.ps1` at the archive root. Release download URLs and extracted-archive commands are unchanged. Download-only bootstraps are separate release assets and are not duplicated inside runtime archives. Historical optional installer names remain accepted in `harness_cli/distribution.py` so existing managed installation receipts still validate.

Previous-version tests are compatibility requirements, not disposable release logs. Artifact compatibility cases live in `test_apply_compatibility.py`; the integration checks also execute immutable old source revisions. Removing a feature may remove tests exclusive to that feature, but moving or combining suites must preserve all other scenarios.

CLI source validation checks both version-specific requirements and declared first-party module imports without executing candidate code. This preserves complete historical layouts while rejecting missing modules introduced by refactors. Project and lifecycle commands share the installer loader, which binds to the selected source directory and does not write bytecode into immutable releases. Project-installer ownership/rollback checks remain separate from CLI storage rules.

## Running checks

Use the dedicated `harness` Conda environment for every Python command:

```bash
conda run -n harness python install.py --root TARGET_PROJECT --dry-run
conda run -n harness python -B -m unittest discover -s tests -v
conda run -n harness python tools/build_release.py --output /tmp/harness-dist
```

Build output must be outside the repository. Only local development builds may use `--allow-dirty`.

Integration checks run explicitly in CI on Linux and Windows. For example:

```bash
conda run -n harness python tests/integration/prepare_release_baselines.py --output /tmp/harness-baselines
conda run -n harness python tests/integration/verify_cli_upgrade.py --baseline /tmp/harness-baselines/v97 --output /tmp/cli-upgrade.json
conda run -n harness python tests/integration/verify_release_upgrade.py --baseline /tmp/harness-baselines/v97 --output /tmp/project-upgrade.json
```

Parser differential checks require the pinned optional `tests/requirements-validation.txt`. Cold installer checks download Miniforge and create an isolated environment; the Windows registry/cold check is restricted to disposable CI runners. These are distinct from unit tests and must not run implicitly during unittest discovery.
