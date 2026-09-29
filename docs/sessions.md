# Project management and native conversations

Harness creates and maintains one project-local harness. Codex uses it through
its native root instructions, agents and skills. Harness adds no bootstrap user
turn. Its local Auto preference record contains thread IDs and booleans only;
Codex remains the owner of conversation history and resume.

```bash
cd /path/to/project
harness-codex init --goal-file PROJECT.md
# Press Enter after init to open Bash with ~/.bashrc loaded.
codex
codex resume
codex resume --last
codex resume SESSION_ID
# Review changed project responsibilities when needed:
harness-codex config --goal-file UPDATED_PROJECT.md
harness-codex status
harness-codex doctor --json
```

`init/config` preserve user text and place a separately owned block in the active
root instruction file (`AGENTS.override.md` before `AGENTS.md`). They do not
create an override to bypass existing guidance. Existing explicit-skill projects
remain readable and migrate to a managed pointer on reviewed `config`.

After successful native integration, interactive Linux `init/config/reset` offers
Enter or yes to open Bash with `~/.bashrc` loaded in the selected project. This is a
child shell; `exit` returns to the original shell. A child process cannot source a
file into its parent. To stay in the original shell, decline and run `source ~/.bashrc`.
`--activate skip` omits the offer; `--activate shell` directly opens the child Bash
on an interactive terminal. JSON, redirected input/output, dry runs and
`--no-codex-integration` never open a shell.

Codex builds the instruction chain when starting a conversation. A resumed
conversation retains native history and model state. If configuration has changed,
ask Codex to re-read the project instructions; use a fresh conversation when a
new native component is unavailable. No automatic user turn is inserted to do this.

Strong integrity and compatibility checks run in `init/config/status/doctor`.
Plain `codex` checks tool updates and Auto capabilities before launch, without
validating or regenerating project artifacts. Generated instructions
require reporting detected managed corruption, preserving the manifest and
consulting `doctor`; ordinary source drift requires a current source read.
These instructions do not constitute a deterministic command gate or proof of
compliance. Inspect questionable installations explicitly before relying on them.

## Migration from v0.12

Run `harness-codex update`, then `harness-codex config` in each project you want to
migrate to native instruction activation. Apply the PATH change in a fresh terminal.
The old `new`, `resume` and `start` commands remain hidden for this release only.
They forward to native Codex with a deprecation notice, without project validation,
GUIDE updates, metadata lookup or activation prompts. Legacy `--ui`, `--settings`
and `--reload-harness` flags do not configure native work sessions; use `/model`.

## Session settings

`init` and `config` first offer Automatic, Manual or Keep native settings. Use Up/Down and Enter on an interactive terminal; redirected or limited terminals use numbered choices. `NO_COLOR` disables selection color. Esc/Ctrl+C cancels before starting a configuration conversation.

```bash
harness-codex init --settings auto --goal-file PROJECT.md
harness-codex config --settings manual
# Work-session settings are selected in native Codex:
codex
```

Automatic selects the catalog's recommended model and its advertised supported default reasoning level for new/configuration work. Resume reads saved settings without loading turns and preserves an available model/effort pair. If that pair is removed or unknown, it selects and reports a supported default before opening the session. No usable resume default requires manual selection. It does not run a separate model to choose a model, infer pricing, or claim command-specific optimal performance. For new work, a catalog with no supported recommendation retains native settings; an empty catalog or connection failure reports an error with the `--settings native` fallback.

Manual lists visible models and supported reasoning levels from the installed Codex catalog. A removed saved model requires a current choice; a removed effort or changed model offers its supported default effort. Choices apply only to this native conversation; global settings remain unchanged. Changing a model after generating a harness does not require regenerating the harness. Supported tools, reasoning choices and output quality may differ by model.

Permissions default to the native policy. Manual choices can request read-only work, workspace/temp writes, or full access. Restricted presets request user review for extra access. Full access requires a separate literal `yes`. Native managed policies still apply. Rejection never triggers a broader retry or silent reviewer change. Keep native settings for custom profiles and hook trust during conversations; full init separately prepares only owned maintenance hooks as described in [maintenance setup](maintenance.md).

## Configuration progress and conversation history

`init`, `config` and applied `reset` use the native Codex App Server. Three stages show generator readiness, configuration and independent file validation. Elapsed seconds update while running. `--details` shows the model summary and session ID; `--interactive` uses the native Codex screen. Questions, incomplete outcomes and approval previews remain visible. The wrapper hides transport JSON, not the native conversation history.

```bash
harness-codex config --timeout 3600
harness-codex config --details
harness-codex config --resume SESSION_ID --goal "The dataset is ..."
harness-codex config --interactive
```

A fresh setup conversation is archived only after a completed model outcome and independently valid project files. Archiving keeps its history but removes it from the ordinary active picker. Interrupted, failed and question-waiting setup conversations stay available. A session explicitly supplied to `config --resume` is never automatically archived. Interactive fallback sessions also stay under native control. Settings discovery uses metadata APIs only and creates no conversation. Native `codex` creates work conversations and native resume reuses them. Existing historical duplicates are not automatically removed.

The default configuration deadline is 1,800 seconds. Ctrl+C, connection failure and timeout close the child connection and preserve project files for inspection. Continue incomplete setup with `config --resume SESSION_ID`. Harness keeps no transport transcript or project session registry.

Command/file approval accepts `yes` with surrounding whitespace ignored; Enter or another answer declines. The progress display confirms the response sent to Codex. This is one-request approval, not a saved command rule or proof of successful execution. Native `failed`/`declined` outcomes are shown separately, even without an exit code, with at most the final 2,000 characters of command output. A model's final explanation is not an approval receipt. Use `config --resume SESSION_ID --interactive --settings native` to inspect the retained conversation and use native approval controls. Host sandbox restrictions still require separate diagnosis; Harness never automatically grants broader access.

## Project brief and guide

`--goal-file` accepts a regular UTF-8 Markdown file, with optional BOM. The old 64 KiB cap is removed. Validation streams the file; the model receives its path and instructions to inspect relevant sections in bounded chunks. Large files are not copied wholesale into the initial prompt. Native access rules still apply to files outside the project. Inline `--goal` and native argument transport retain their finite limits; use a file for a large brief.

The CLI maintains `.harness/GUIDE.md` after successful init/config. The same path is refreshed for the current tool/harness revision; unchanged content is not rewritten. A checksum marker distinguishes the unchanged CLI guide from user edits. Edited or unrelated guides are preserved, not overwritten or deleted. Existing unknown guide copies are not treated as owned. `remove` and `reset` include an unchanged owned guide in the ordinary recoverable removal transaction.

## Diagnostics and execution restrictions

Human output states that checks cover project files and contracts. `runtimeLoading: not-tested` and `taskQuality: not-measured` remain in `--json` because static validation cannot prove live component loading or task quality. They are not generation errors or counters that become successful after a fixed number of sessions. Live discovery requires an observed native session; correctness and harness benefit require a concrete task and the separate opt-in evaluation workflow. See [evaluation](evaluation.md).

During configuration, native command failures mentioning bubblewrap, namespace setup or `RTM_NEWADDR` receive host/container troubleshooting guidance. Approval-limit failures receive reviewer guidance. Harness does not configure bubblewrap, weaken the sandbox, or reset approval budgets. Reproduce a simple file read in native Codex under the same environment and inspect host namespace settings. In interactive work sessions, native Codex owns the error display; Harness does not intercept its terminal or claim to repair the host.
