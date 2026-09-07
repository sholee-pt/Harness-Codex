Harness for Codex v9.5 fixes installation completeness checks and process environment inheritance, and adds deadlines to bootstrap Git operations.

- Incomplete v9.4+ sources missing `lifecycle.py`, or v9.5+ sources missing `environment.py`, are refused before installation state or release output is created. Real v9.2/v9.3/v9.4 installation and upgrade paths remain supported.
- Harness uses its dedicated Conda Python while Codex inherits the calling terminal's PATH and Conda labels. Activate your project environment before starting Harness. Diagnostic helpers receive a separate Harness environment.
- Existing v9.2–v9.4 launchers need a guarded, offline migration. After updating, run the commands below. If an interactive command repairs its launcher and asks you to repeat it, run it again from the same terminal; the affected invocation does not launch Codex.
- Bootstrap `--timeout SECONDS` limits each Git query/fetch independently (default 120; integer 1–600). It terminates the process group, escalates after two seconds, removes temporary files and preserves the existing installation. Initial curl, Conda and total installation time are not covered. Linux requires GNU coreutils `timeout` and `sleep` in addition to Bash, Git, tar and Conda.
- Manifest Schema 7, Artifact Contract 2 and all generated-project schemas remain unchanged. Valid v9.0–v9.5 projects remain compatible; updating the CLI does not regenerate project files.

```bash
harness update
harness update --repair-launcher
# Activate the project's existing environment in this terminal, if needed.
harness start --project /path/to/project
```

Linux/Windows tests, pinned real-source upgrade checks, process-environment probes, Linux timeout regressions and an authenticated GitHub bootstrap check gate publication. Environment probes use an inert Codex substitute; they do not establish native skill/agent discovery, agent performance, task-time reduction or token savings, and are not a verification of authentication on another user's server. Claude integration remains unimplemented.
