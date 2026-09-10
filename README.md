<h1 align="center">Harness for Codex <img src="https://img.shields.io/badge/Beta-F59E0B.svg?style=flat-square" alt="Beta" height="24"></h1>

<p align="center">
  Project-local orchestration with Codex-native agents and skills.
</p>

<p align="center">
  <a href="https://github.com/sholee-pt/Harness/releases/tag/codex-v0.10.0-beta"><img src="https://img.shields.io/badge/Version-v0.10.0--beta-2563EB.svg?style=flat-square" alt="Version: v0.10.0-beta"></a>
  <a href="#agent-editions"><img src=".github/badges/agent-codex.svg" alt="Agent: Codex"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Proprietary-64748B.svg?style=flat-square" alt="License: Proprietary"></a>
</p>

<p align="center">
  <a href="environment.yml"><img src="https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <a href="#for-linux"><img src=".github/badges/platform.svg" alt="Platform: Linux and Windows"></a>
</p>

<p align="center">
  <a href="#for-linux">Linux install</a> &middot;
  <a href="#for-windows">Windows install</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="https://github.com/sholee-pt/Harness/releases/tag/codex-v0.10.0-beta">Release</a> &middot;
  <a href="CHANGELOG.md">Changelog</a>
</p>

Generate and maintain one shared project harness with Codex-native agents and skills. Use **`harness-codex`** to configure it, start new conversations, or resume existing ones. Plain folders, Git worktrees and workspaces containing multiple repositories are supported.

**Development beta:** Harness is still under development and testing.

## Installation Guide

### For Linux

```bash
curl -fsSL https://github.com/sholee-pt/Harness/releases/download/codex-v0.10.0-beta/install_harness_codex.sh | sh
harness-codex --version
```

Supports Linux x86_64 and aarch64. Requires curl, Bash, tar and sha256sum. The installer verifies the release checksum, prepares an isolated Python 3.11 environment and Git, installs the command in `~/.local/bin`, and registers PATH in `~/.bashrc`. No sudo is required. After installation, press Enter or type yes to open a new Bash with ~/.bashrc loaded. Exit returns to the original shell. To stay in the original shell instead, run `source ~/.bashrc` yourself. Redirected installation skips this prompt.

### For Windows

Run in **64-bit Windows PowerShell 5.1 or PowerShell 7** on Windows x64:

```powershell
irm https://github.com/sholee-pt/Harness/releases/download/codex-v0.10.0-beta/install_harness_codex.ps1 | iex
harness-codex --version
```

The installer verifies the ZIP checksum, prepares an isolated Python 3.11 environment and Git, and adds the command to your user PATH. It also updates PATH in the current PowerShell session. Administrator access is not required.

If installation traces exist, choose **`reuse`** to retain tool preferences or **`reset`** to reset Harness update preferences, its check cache and managed PATH registration. Project harnesses and unrelated settings are preserved. Unattended installation accepts `--existing reuse|reset` on Linux or `-Existing reuse|reset` on Windows. See [installation options](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/installation.md).

## Quick Start

Install and sign in to [Codex CLI](https://developers.openai.com/codex/cli/) separately. Harness uses its native login, model, trust, sandbox and approval settings.

```bash
cd /path/to/project
harness-codex init --goal-file PROJECT.md
harness-codex new "Fix the preprocessing failure and run the tests"
harness-codex resume
```

`PROJECT.md` is an optional UTF-8 Markdown brief describing the project's purpose, responsibilities and constraints. `init` uses Codex to inspect the project and create its harness, showing live stages and elapsed seconds instead of the internal setup prompt. Native approval requests and additional questions remain visible. It then validates the resulting files. Existing harnesses are reported and retained. You can also provide a short description with `--goal "..."`, or run `init` without a brief.

Choose a model, reasoning level and permissions from the configuration menu; Enter keeps current Codex settings. Three concise stages show progress and file validation. `--settings native` skips the menu; `--details` includes the model's final summary. Questions and approvals remain visible. If your Codex version needs the full conversation screen, use `--interactive`. Continue unfinished configuration with `harness-codex config --resume SESSION_ID --goal "Your answer"`. See [configuration progress](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/sessions.md#configuration-progress).

### Conversations and project maintenance

| Command | Purpose and example |
| --- | --- |
| `init` | Create the project harness once: `harness-codex init --goal-file PROJECT.md` |
| `new [TASK]` | Start a fresh conversation sharing the existing harness: `harness-codex new "Implement CSV import"` |
| `resume [SESSION_ID]` | Open the native conversation picker, or resume a specific ID |
| `resume --last` | Resume the latest native conversation for the selected project |
| `config` | Refresh the owned generator and review the existing project harness in Codex |
| `maintenance` | Inspect opt-in maintenance; `--mode suggest` enables review notices, `--mode auto` permits bounded existing-skill corrections |
| `status` | Read-only installation, compatibility and evidence status, with a suggested next command |
| `doctor` | Read-only ownership, manifest, references and activation checks |
| `update --check` | Check for a newer tool version without installing it |
| `update` | Update the tool; project agents and skills are reviewed separately |
| `remove` | Preview removal of the project's unchanged generated harness files |
| `reset` | Preview removal and fresh configuration of the project harness |
| `uninstall` | Remove the tool and its recorded installation settings after typing `yes` |

Reports are concise by default. Add `--json` to `status`, `doctor`, update checks or previews for the complete diagnostic report. `new` and `resume` keep the native Codex conversation screen and its visible harness activation message.

Project commands default to the current directory. Add `--project "/path/to/project"` to select another folder. `start` remains a deprecated alias for `new`; `configure` remains an alias for `config`.

Every `new` and `resume` validates and uses the **current shared harness**, without copying or regenerating it. Resume retains Codex's conversation history. Run `config` explicitly when the harness needs revising. See [session lifecycle](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/sessions.md).

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

After reinstalling, run `status` in a project to recognize its retained harness. Reuse it with `new`/`resume`, review it with `config`, or explicitly `reset` it. Remove project harnesses before uninstalling if you no longer need them; the tool never searches your disk to delete projects.

## Documentation

- [Installation, reinstall choices and troubleshooting](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/installation.md)
- [Project and conversation lifecycle](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/sessions.md)
- [Bounded maintenance and local records](docs/maintenance.md)
- [Beta versioning and migration](docs/versioning.md)
- [Generated structure and design](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/architecture.md)
- [Quality evaluation and optional local evidence](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/evaluation.md)
- [Release assets and verification](https://github.com/sholee-pt/Harness/blob/codex/v0.10.0-beta/docs/distribution.md)
- [Changelog](CHANGELOG.md) · [GitHub Releases](https://github.com/sholee-pt/Harness/releases) · [Contributing](CONTRIBUTING.md)

## Agent editions

This edition provides **`harness-codex`** and needs no `--agent` option. The future Claude command is `harness-claude`. Hidden legacy Codex selectors remain accepted for older scripts. Claude development is maintained separately on `claude/*` branches; this command does not implement Claude sessions.

## License

See [LICENSE](LICENSE) for the current terms. Repository visibility does not change the license.
