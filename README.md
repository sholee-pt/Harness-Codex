<h1 align="center">Harness for Codex <img src="https://img.shields.io/badge/Beta-F59E0B.svg?style=flat-square" alt="Beta" height="24"></h1>

<p align="center">
  Project-local orchestration with Codex-native agents and skills.
</p>

<p align="center">
  <a href="https://github.com/sholee-pt/Harness-Codex/tree/v0.34.0-beta"><img src="https://img.shields.io/badge/Version-v0.34.0--beta-2563EB.svg?style=flat-square" alt="Version: v0.34.0-beta"></a>
  <a href="#agent-editions"><img src=".github/badges/agent-codex.svg" alt="Agent: Codex"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Proprietary-64748B.svg?style=flat-square" alt="License: Proprietary"></a>
</p>

<p align="center">
  <a href="environment.yml"><img src="https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <a href="#installation-guide"><img src=".github/badges/platform.svg" alt="Platform: Linux and Windows"></a>
</p>

<p align="center">
  <a href="#for-linux">Linux install</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="https://github.com/sholee-pt/Harness-Codex/releases">Release</a> &middot;
  <a href="CHANGELOG.md">Changelog</a>
</p>

Generate and maintain one shared project harness with Codex-native agents and skills. **Harness-Codex configures and maintains the project harness. Codex owns conversations and interactive work.** Plain folders, Git worktrees and workspaces containing multiple repositories are supported.

**Development beta:** Harness is still under development and testing.

## Installation Guide

### For Linux

**Latest release: [v0.32.3-beta](https://github.com/sholee-pt/Harness-Codex/releases/tag/v0.32.3-beta)**

```bash
curl -fsSL https://github.com/sholee-pt/Harness-Codex/releases/download/v0.32.3-beta/install_harness_codex.sh | sh
```

Previous releases retain their version tags and installation commands on the [Releases page](https://github.com/sholee-pt/Harness-Codex/releases).

To install the development source instead:

```bash
git clone --branch v0.34.0-beta --single-branch https://github.com/sholee-pt/Harness-Codex.git Harness-Codex
bash Harness-Codex/installer/install.sh
harness-codex --version
```

Supports Linux x86_64 and aarch64. Source cloning requires Git; installation requires curl, Bash, tar and sha256sum. The installer validates the tool payload, prepares an isolated Python 3.11 environment and Git, installs the command in `~/.local/bin`, and registers PATH in `~/.bashrc`. Published release installation additionally verifies its archive checksum. No sudo is required. After installation, press Enter or type yes to open a new Bash with ~/.bashrc loaded. Exit returns to the original shell. To stay in the original shell instead, run `source ~/.bashrc` yourself. Redirected installation skips this prompt.

### For Windows

Windows release assets are not currently available. Windows support remains in the source tree, but publication is paused until its separate validation passes. Use Windows release installation only when the [release assets](https://github.com/sholee-pt/Harness-Codex/releases) include `install_harness_codex.ps1`, `harness-codex-VERSION-windows.zip` and the matching Windows native package. See [source installation options](docs/installation.md) for development use.

When migrating from 0.10.0-beta, run this installer once: its updater cannot discover the new unprefixed branches. If installation traces exist, choose **`reuse`** to retain tool preferences or **`reset`** to reset Harness update preferences, its check cache and managed PATH registration. Project harnesses and unrelated settings are preserved. Unattended installation accepts `--existing reuse|reset` on Linux or `-Existing reuse|reset` on Windows. See [installation options](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/installation.md).

## Quick Start

Default Linux installation also prepares the official Codex command. Codex handles login and retains its native model, trust, sandbox and approval settings. After applying PATH, you can start setup entirely from its screen:

```bash
codex
```

Enter `/harness/`, select **Init**, choose a project directory and supply a description or Markdown path. Confirm the summary to configure that project. An existing harness offers review and update. For another directory, finish the current work and use `/quit`; Harness opens the target conversation and continues setup there. Use **Settings** for project preferences, **Jev** for private login, and **Tool** for updates or uninstall. Credential entry and tool removal open their terminal flows after exiting Codex. See [in-conversation management](docs/management.md).

The terminal workflow remains available:

The configuration picker and login prompts described below apply to terminal
`harness-codex init`. In the Codex menu, configuration uses the current conversation
settings; use **Settings** for maintenance/routing and **Jev → Login** for credentials.

```bash
cd /path/to/project
harness-codex init --goal-file PROJECT.md
# Press Enter after init to open Bash with ~/.bashrc loaded.
# Or stay in the current shell and run: source ~/.bashrc
codex
codex resume
codex resume --last
```

`PROJECT.md` is an optional UTF-8 Markdown brief describing the project's purpose, responsibilities and constraints. `init` uses Codex to inspect the project and create its harness, showing live stages and elapsed seconds instead of the internal setup prompt. Native approval requests and additional questions remain visible. It then validates the resulting files. Existing harnesses are reported and retained. You can also provide a short description with `--goal "..."`, or run `init` without a brief.

On Linux, `init` also prepares local Graft retrieval and enables Jev shadow advice automatically. The first setup downloads Graft's isolated runtime; subsequent projects reuse it. If no TypeSafe key is available, init guides you to its key page and accepts hidden input once, saving it for later projects without shell exports or restart. A newly entered key uses one small authentication request; existing credentials make no init API call. You can skip login and continue ordinary retrieval. Eligible Jev queries may send bounded code snippets to TypeSafe. Use `--retrieval off` to skip both setups, or `harness-codex jev disable` to keep only local retrieval. Explicit opt-outs survive repeated init. See [retrieval controls](docs/retrieval.md) and [Jev authentication and behavior](docs/jev.md).

Choose **Automatic** or **Manual** with the arrow keys and Enter. Automatic uses the recommended default from your Codex catalog for configuration. Manual offers the available models, reasoning levels and permissions. `--settings auto|manual|native` selects a mode directly. Three concise stages show configuration progress and file validation. Questions and approvals stay visible. See [session settings](docs/sessions.md#session-settings).

After successful setup, interactive `init` offers two project preferences: **maintenance** (`off`, `suggest`, `auto`) and **observed-outcome advice for Auto** (`off`, `on`). Each menu explains its effect; Enter keeps the current setting. New projects start with both off. Maintenance reviews can use conversation tokens; local Auto advice makes no extra model call and needs recorded quality feedback. Change either later with `harness-codex maintenance --mode suggest` or `harness-codex routing --adaptive on`. These commands and status checks are also listed in `.harness/GUIDE.md`. See [maintenance](docs/maintenance.md) and [Auto advice](docs/routing.md#optional-outcome-based-auto-advice).

`init` also registers and trusts only Harness maintenance hooks through Codex's native interface, even when both preferences are off. Trust stays ready when a project feature is enabled later; it does not enable the feature. Use `init --hook-trust manual` to leave trust unchanged. Unsupported Codex capabilities or managed restrictions produce manual guidance instead.

### Conversations and project maintenance

Inside an integrated Codex conversation, type `/harness/status` for the boxed
dashboard or `/harness/settings` for preferences. `/harness/init` and
`/harness/config` use the current conversation for generation and review.
These qualified inputs are handled by the adapter; they are not entries in the
built-in `/` completion menu. Terminal commands remain available. See
[management commands, project switching and removal](docs/management.md).

After `init`, run **`codex`** and select **Auto** at the top of `/model`.
The integration downloads an unmodified official Codex release and connects its
original terminal to a local Auto adapter. The composer, colors, shortcuts,
approvals and native history remain Codex-owned. Your separately installed Codex
is preserved. Codex updates no longer require a Harness-specific Codex build.

Each interactive launch checks official Codex and published Harness releases.
An arrow-key menu offers **update both**, **Codex only**, **Harness only**, or
**skip this time** when applicable. Downloads begin only after your selection,
before the conversation opens. Offline checks continue with installed files.

The model footer identifies **Auto, the selected model and reasoning level** while Auto is enabled.
Clear new tasks and complexity increases can change the selection immediately;
two consecutive clearly lighter requests allow a lower tier. Ambiguous follow-ups
keep the current selection. These are routing rules, not measured performance rankings.

For Auto to start enabled, configure with `--auto-model auto`; otherwise native
model defaults remain in effect until you select Auto. This preference is owned
by Harness and does not rewrite global Codex settings. The Auto integration
is currently validated on Linux x86_64. Linux aarch64 packages are resolved from
official releases but are not covered by the x86_64 terminal gate. On unsupported platforms, use
`--no-codex-integration` with a separately installed Codex; Auto is unavailable.
See [integration and routing](docs/routing.md).

| Command | Purpose and example |
| --- | --- |
| `init` | Create the project harness once: `harness-codex init --project PATH --goal-file PROJECT.md`. Missing project directories are created. |
| `context` | Inspect the current host or resolve an old project path after changing servers/mounts. See [portable workspaces](docs/sessions.md#shared-mounts-and-server-changes). |
| `config` | Refresh the owned generator and review the existing project harness in Codex |
| `maintenance` | Inspect opt-in maintenance; `--mode suggest` enables review notices, `--mode auto` permits bounded existing-skill corrections |
| `routing --adaptive status` | Inspect local Auto evidence; `--adaptive on` or `off` changes its use without selecting a model |
| `status` | Read-only installation, compatibility and evidence status, with a suggested next command |
| `doctor` | Read-only ownership, manifest, references and activation checks |
| `skills` | List project skills; `skills add --source PATH --dry-run` previews a reviewed local specialist skill import |
| `update --check` | Check for a newer published Harness release without installing it |
| `update` | Update Harness and migrate an existing integration; project agents and skills are reviewed separately |
| `remove` | Preview removal of the project's unchanged generated harness files |
| `reset` | Preview removal and fresh configuration of the project harness |
| `uninstall` | Preview the removal scope, then confirm with Enter or `y`; cancel with `n` |

Reports are concise by default. Add `--json` to `status`, `doctor`, update checks or previews for the complete diagnostic report. Native `codex` starts and resumes work without an artificial Harness activation message.

Project commands default to the current directory. Add `--project "/path/to/project"` to select another folder. `configure` remains an alias for `config`.

`init/config` validate the project after configuration; `status/doctor` perform
explicit checks. Codex reads the managed block in the active root instructions
and the project router. Source drift prompts review without preventing Codex
from starting. Detected managed-file corruption directs you to `doctor`.
One owned `.harness/GUIDE.md` is maintained during configuration. Ordinary Codex
conversations do not rewrite it. See [project lifecycle](docs/sessions.md).

### Update an existing project harness

```bash
harness-codex update
harness-codex status
# When the project generator needs updating:
harness-codex config
```

Compatible existing project harnesses can be reused. Source changes may require refreshing evidence; changed managed files require review. A valid status confirms file contracts, not measured model quality or token savings.

Optional maintenance can be enabled once with `harness-codex maintenance --mode suggest` or `--mode auto`. Successful automatic hook setup during `init` removes the need for a separate trust step. Ordinary turns do not launch an extra review model; scope growth alone never requires additional agents. See [maintenance limits and records](docs/maintenance.md).

### Remove, reset or uninstall

```bash
# Preview, then remove the project's generated harness and its generator:
harness-codex remove --include-generator
harness-codex remove --include-generator --yes

# Alternatively, review a fresh project configuration:
harness-codex reset
harness-codex reset --yes --goal-file PROJECT.md

# Remove the installed tool after reviewing the preview:
harness-codex uninstall --dry-run
harness-codex uninstall
# Enter/y/yes: confirm; n/no: cancel
```

Uninstall preserves project harnesses, native Codex conversations and pre-existing Conda environments. It removes the verified tool installation, its removable PATH registration and unchanged files in a runtime created exclusively for this installation. Added or modified files and shared PATH entries are preserved and reported. Windows finishes runtime cleanup after the command exits.

After reinstalling, run `status` in a project to recognize its retained harness. Reuse it with `codex`/`codex resume`, review it with `config`, or explicitly `reset` it. Remove project harnesses before uninstalling if you no longer need them; the tool never searches your disk to delete projects.

## Documentation

- [Native Codex integration and automatic model routing](docs/routing.md)
- [Installation, reinstall choices and troubleshooting](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/installation.md)
- [Project and conversation lifecycle](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/sessions.md)
- [Bounded maintenance and local records](docs/maintenance.md)
- [Optional task checkpoints and selective resume](.agents/skills/harness/references/task-checkpoints.md)
- [Optional local Graft retrieval](docs/retrieval.md)
- [Optional Jev advice, local observations and evaluation limits](docs/jev.md)
- [Dependency and optimization review](docs/optimization-review.md)
- [Beta versioning and migration](docs/versioning.md)
- [Generated structure and design](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/architecture.md)
- [Quality evaluation and optional local evidence](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/evaluation.md)
- [Workflow efficiency, instruction inventory and selected OMX concepts](docs/workflow-efficiency.md)
- [External specialist skills and selected upstream improvements](docs/external-skills.md)
- [Release assets and verification](https://github.com/sholee-pt/Harness-Codex/blob/v0.34.0-beta/docs/distribution.md)
- [Changelog](CHANGELOG.md) · [GitHub Releases](https://github.com/sholee-pt/Harness-Codex/releases) · [Contributing](CONTRIBUTING.md)

## Agent editions

This repository provides **`harness-codex`** and needs no `--agent` option. Hidden legacy Codex selectors remain accepted for older scripts. Claude integration is outside this repository; this command does not implement Claude sessions.

## License

See [LICENSE](LICENSE) for the current terms. Repository visibility does not change the license.
