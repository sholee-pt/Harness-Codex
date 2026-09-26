<h1 align="center">Harness for Codex <img src="https://img.shields.io/badge/Beta-F59E0B.svg?style=flat-square" alt="Beta" height="24"></h1>

<p align="center">
  Project-local orchestration with Codex-native agents and skills.
</p>

<p align="center">
  <a href="https://github.com/sholee-pt/Harness-Codex/releases/tag/v0.22.2-beta"><img src="https://img.shields.io/badge/Version-v0.22.2--beta-2563EB.svg?style=flat-square" alt="Version: v0.22.2-beta"></a>
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
  <a href="https://github.com/sholee-pt/Harness-Codex/releases/tag/v0.22.2-beta">Release</a> &middot;
  <a href="CHANGELOG.md">Changelog</a>
</p>

Generate and maintain one shared project harness with Codex-native agents and skills. **Harness-Codex configures and maintains the project harness. Codex owns conversations and interactive work.** Plain folders, Git worktrees and workspaces containing multiple repositories are supported.

**Development beta:** Harness is still under development and testing.

## Installation Guide

### For Linux

```bash
curl -fsSL https://github.com/sholee-pt/Harness-Codex/releases/download/v0.22.2-beta/install_harness_codex.sh | sh
harness-codex --version
```

Supports Linux x86_64 and aarch64. Requires curl, Bash, tar and sha256sum. The installer verifies the release checksum, prepares an isolated Python 3.11 environment and Git, installs the command in `~/.local/bin`, and registers PATH in `~/.bashrc`. No sudo is required. After installation, press Enter or type yes to open a new Bash with ~/.bashrc loaded. Exit returns to the original shell. To stay in the original shell instead, run `source ~/.bashrc` yourself. Redirected installation skips this prompt.

### For Windows

Windows availability is version-specific. When the release includes `install_harness_codex.ps1`, `harness-codex-VERSION-windows.zip` and the Windows native package, download the PowerShell installer from that release and run it under your normal script execution policy:

```powershell
Invoke-WebRequest 'https://github.com/sholee-pt/Harness-Codex/releases/download/v0.22.2-beta/install_harness_codex.ps1' -OutFile ./install_harness_codex.ps1
& ./install_harness_codex.ps1
harness-codex --version
```

When migrating from 0.10.0-beta, run this installer once: its updater cannot discover the new unprefixed branches. If installation traces exist, choose **`reuse`** to retain tool preferences or **`reset`** to reset Harness update preferences, its check cache and managed PATH registration. Project harnesses and unrelated settings are preserved. Unattended installation accepts `--existing reuse|reset` on Linux or `-Existing reuse|reset` on Windows. See [installation options](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/installation.md).

## Quick Start

Install and sign in to [Codex CLI](https://developers.openai.com/codex/cli/) separately. Harness uses its native login, model, trust, sandbox and approval settings.

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

### Conversations and project maintenance

After `init`, run **`codex`** and select **Auto** at the top of `/model`.
The integration installs a pinned original Codex CLI 0.154.0 build with a bounded
Auto extension. It retains the original composer, colors, menus, shortcuts,
attachments, approvals, authentication and history. Your original Codex binary
is preserved separately. No Harness conversation launcher is required.

The model footer displays **`Auto selected: MODEL REASONING`** while Auto is enabled.
Clear new tasks and complexity increases can change the selection immediately;
two consecutive clearly lighter requests allow a lower tier. Ambiguous follow-ups
keep the current selection. These are routing rules, not measured performance rankings.

For Auto to start enabled, configure with `--auto-model auto`; otherwise native
model defaults remain in effect until you select Auto. This preference is owned
by Harness and does not rewrite global Codex settings. The Auto integration
is currently released for Linux x86_64. On unsupported architectures, use
`--no-codex-integration` with a separately installed Codex; Auto is unavailable.
See [integration and routing](docs/routing.md).

| Command | Purpose and example |
| --- | --- |
| `init` | Create the project harness once: `harness-codex init --goal-file PROJECT.md` |
| `config` | Refresh the owned generator and review the existing project harness in Codex |
| `maintenance` | Inspect opt-in maintenance; `--mode suggest` enables review notices, `--mode auto` permits bounded existing-skill corrections |
| `status` | Read-only installation, compatibility and evidence status, with a suggested next command |
| `doctor` | Read-only ownership, manifest, references and activation checks |
| `skills` | List project skills; `skills add --source PATH --dry-run` previews a reviewed local specialist skill import |
| `update --check` | Check for a newer tool version without installing it |
| `update` | Update the tool and an installed Auto integration; project agents and skills are reviewed separately |
| `remove` | Preview removal of the project's unchanged generated harness files |
| `reset` | Preview removal and fresh configuration of the project harness |
| `uninstall` | Remove the tool and its recorded installation settings after typing `yes` |

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

Optional maintenance can be enabled once with `harness-codex maintenance --mode suggest` or `--mode auto`. Review the handler in Codex `/hooks`. Ordinary turns do not launch an extra review model; scope growth alone never requires additional agents. See [maintenance limits and records](docs/maintenance.md).

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
# Type exactly: yes
```

Uninstall preserves project harnesses, native Codex conversations and pre-existing Conda environments. It removes the verified tool installation, its removable PATH registration and unchanged files in a runtime created exclusively for this installation. Added or modified files and shared PATH entries are preserved and reported. Windows finishes runtime cleanup after the command exits.

After reinstalling, run `status` in a project to recognize its retained harness. Reuse it with `codex`/`codex resume`, review it with `config`, or explicitly `reset` it. Remove project harnesses before uninstalling if you no longer need them; the tool never searches your disk to delete projects.

## Documentation

- [Native Codex integration and automatic model routing](docs/routing.md)
- [Installation, reinstall choices and troubleshooting](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/installation.md)
- [Project and conversation lifecycle](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/sessions.md)
- [Bounded maintenance and local records](docs/maintenance.md)
- [Optional task checkpoints and selective resume](.agents/skills/harness/references/task-checkpoints.md)
- [Optional local Graft retrieval](docs/retrieval.md)
- [Optional Jev advice, local observations and evaluation limits](docs/jev.md)
- [Dependency and optimization review](docs/optimization-review.md)
- [Beta versioning and migration](docs/versioning.md)
- [Generated structure and design](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/architecture.md)
- [Quality evaluation and optional local evidence](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/evaluation.md)
- [Workflow efficiency, instruction inventory and selected OMX concepts](docs/workflow-efficiency.md)
- [External specialist skills and selected upstream improvements](docs/external-skills.md)
- [Release assets and verification](https://github.com/sholee-pt/Harness-Codex/blob/v0.22.2-beta/docs/distribution.md)
- [Changelog](CHANGELOG.md) · [GitHub Releases](https://github.com/sholee-pt/Harness-Codex/releases) · [Contributing](CONTRIBUTING.md)

## Agent editions

This repository provides **`harness-codex`** and needs no `--agent` option. Hidden legacy Codex selectors remain accepted for older scripts. Claude integration is outside this repository; this command does not implement Claude sessions.

## License

See [LICENSE](LICENSE) for the current terms. Repository visibility does not change the license.
