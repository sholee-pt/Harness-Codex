# Installation and troubleshooting

The [README installation guide](../README.md#installation-guide) provides the standard commands. Release installers are version-bound; subsequent `harness-codex update` follows published Harness releases. Explicit `--branch` pins retain the developer source-update path.

For the transition from a patched Codex installation, run the current release installer with `--existing reuse`, then `harness-codex config` once. This preserves project artifacts and moves the owned PATH entry to the official-release adapter. An older updater can install the new management source but still report a missing old-style native package; running the now-updated `config` completes that transition. Subsequent official Codex updates require no Harness rebuild. Auto's WebSocket dependency is prepared in the selected Harness interpreter during integration setup.

Interactive `codex` launches check both release channels and require a selection before downloads. Both historical `compatible` and `check` settings now request consent; `off` and `HARNESS_NO_UPDATE_CHECK=1` skip checks. Help, version, doctor, dry runs and noninteractive Codex commands do not check releases. For private GitHub access, an explicitly configured `HARNESS_GITHUB_TOKEN` or `GH_TOKEN` can authorize API calls; Git user.name/email are not authentication. Credentials are never forwarded to asset redirects.

Current releases and CI target Linux. Windows installation code and the option references below are retained for future work; no Windows installer or native package is published while Windows validation is paused.

## Options

| Linux | Windows | Effect |
| --- | --- | --- |
| `--data-dir PATH` | `-DataDir PATH` | Managed CLI storage |
| `--bin-dir PATH` | `-BinDir PATH` | Command directory |
| `--auto-update compatible\|check\|off` | `-AutoUpdate compatible\|check\|off` | Between-session update policy |
| `--existing ask\|reuse\|reset` | `-Existing ask\|reuse\|reset` | Existing-installation choice |
| `--activate ask\|shell\|skip` | — | Ask to open a child Bash, open it explicitly, or skip activation |
| `--no-modify-path` | `-NoModifyPath` | Skip PATH registration |
| `CONDA_EXE=/path/to/conda` | `-CondaExe PATH` | Use an existing environment manager |
| — | `-CondaHome PATH` | Select a dedicated Miniforge location |

`reuse` retains the repository transport and automatic-update policy. Branch pins are retained except for the [one-time legacy-to-beta migration](versioning.md). `reset` applies the supplied/default preferences, clears the update-check cache and rebuilds the exact managed PATH registration. Both preserve verified releases and runtime files, project harnesses, unrelated shell/registry settings and modified user content. Reset does not authorize removing unknown directories. Without a terminal, an existing installation requires an explicit choice.

```bash
curl -fsSL https://github.com/sholee-pt/Harness-Codex/releases/download/v0.23.2-beta/install_harness_codex.sh | sh -s -- --existing reuse
source ~/.bashrc
```

For Windows source development, run from an existing checkout:

```powershell
./installer/install.ps1 -Existing reset
```

## Source installation

```bash
git clone --branch v0.23.2-beta --single-branch https://github.com/sholee-pt/Harness-Codex.git
bash Harness-Codex/installer/install.sh
source ~/.bashrc
```

On Windows, the source installer can be exercised from PowerShell for development: `& ./Harness-Codex/installer/install.ps1` under your normal script execution policy. This does not establish a verified Windows native release. The source scripts install an existing checkout; `install_harness_codex.sh` and `.ps1` first download a release and then invoke the corresponding source installer. Installation does not alter project Git state.

## PATH and logs

The source installer resolves the selected Conda environment and executes its
absolute Python path. It checks the actual Python prefix against the selected
prefix before creating installation state. A conflicting Python earlier on PATH
does not select the interpreter. Expected/actual interpreter details are recorded
in the diagnostic log; parent-shell and project environment settings are preserved.

The Linux installer asks whether to open a new Bash after installation. Enter or yes opens an interactive child shell that reads `~/.bashrc`; `exit` returns to the original shell. This executes your existing Bash startup instructions, including any environment initialization you have configured. It does not modify the parent shell. Choose no to skip. To apply settings in the original Bash, run **`source ~/.bashrc`**, or open a new terminal. Running `~/.bashrc` as a command tries to execute it and may report permission denied; executable permissions are not needed to source it. Use `~/.local/bin/harness-codex --version` to distinguish PATH lookup from command installation. A `bash installer/install.sh` child cannot export variables back into its parent shell. GitHub CLI is not required.

Windows registers user PATH and refreshes the current PowerShell PATH. Other open terminals need restarting. A shared bin directory may remain on PATH after uninstall to preserve other commands.

The installer displays an animated indicator and live elapsed seconds on an interactive terminal, with a detailed log location. It pauses animation while asking for a reinstall choice. Noninteractive/redirected output contains ordinary stage lines; Linux skips child-shell activation when there is no controlling terminal or `--no-modify-path` is selected. Failed downloads, environment setup or installation retain a diagnostic log. Colors are presentation only; redirected output remains readable. An incomplete pre-existing environment is preserved for review instead of being overwritten.

## Ownership and uninstall

The CLI removes only verified files from its own installation. New dedicated runtime files have immutable SHA-256 ownership receipts. Added or changed runtime files are retained and reported; reused and legacy Conda installations have no inferred ownership and remain installed. Temporary failure logs and other historical untracked files are not deleted by matching their names.

Project harnesses survive tool uninstall. Reinstall, select the same project and run `status`: no global registry is needed because its manifest is stored in the project. Use native `codex` for a compatible harness, update its generator and run `config` when needed, or explicitly `reset`. `remove --include-generator --yes` removes the unchanged owned project installation before tool uninstall if desired. Native Codex history and credentials belong to Codex and remain untouched.

Confirmed uninstall removes the owned saved TypeSafe credential, while preserving project harnesses and Graft/Jev observations. Environment keys are not changed. Unsafe or unrecognized credential storage is preserved and reported. Use `harness-codex jev login` after reinstall to connect TypeSafe again; see [Jev authentication](jev.md#login-and-saved-credentials).
