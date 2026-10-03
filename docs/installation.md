# Installation and troubleshooting

The [README installation guide](../README.md#installation-guide) provides the standard commands. Release installers are version-bound; subsequent `harness-codex update` follows published Harness releases. Explicit `--branch` pins retain the developer source-update path.

For the transition from a patched Codex installation, run the current release installer with `--existing reuse`, then `harness-codex config` once. This preserves project artifacts and moves the owned PATH entry to the official-release adapter. An older updater can install the new management source but still report a missing old-style native package; running the now-updated `config` completes that transition. Subsequent official Codex updates require no Harness rebuild. Auto's WebSocket dependency is prepared in the selected Harness interpreter during integration setup.

Interactive `codex` launches check both release channels and require a selection before downloads. Both historical `compatible` and `check` settings now request consent; `off` and `HARNESS_NO_UPDATE_CHECK=1` skip checks. Help, version, doctor, dry runs and noninteractive Codex commands do not check releases. For private GitHub access, an explicitly configured `HARNESS_GITHUB_TOKEN` or `GH_TOKEN` can authorize API calls; Git user.name/email are not authentication. Credentials are never forwarded to asset redirects.

Interactive launch shows progress while checking releases and Auto compatibility. A failed release check keeps installed files available. Native fallback preserves Codex settings and history, but disables both Harness Auto and `/harness/` management for that session. The terminal displays `status`, `init` and `config` commands for the selected project; run them after exiting Codex. An explicit native profile or `HARNESS_CODEX_NATIVE=1` keeps its original arguments and receives the same management guidance. Help and automation remain quiet native commands.

Current releases and CI target Linux. Windows installation code and the option references below are retained for future work; no Windows installer or native package is published while Windows validation is paused.

## Options

The default Linux install prepares the official Codex package and registers the
Harness-aware `codex` entry point. After applying PATH, run `codex` and select Init
from `/harness/`; no project CLI command is required first. Native account login
and project trust still belong to Codex. Downloads or integration failures stop
the installer before its completion message; rerun with `--existing reuse` after
resolving them. `--no-codex-integration` keeps a tool-only install, while
`--no-modify-path` also skips automatic integration. Existing registered entry
points are preserved by either opt-out; they are not uninstalled.

| Linux | Windows | Effect |
| --- | --- | --- |
| `--data-dir PATH` | `-DataDir PATH` | Managed CLI storage |
| `--bin-dir PATH` | `-BinDir PATH` | Command directory |
| `--auto-update compatible\|check\|off` | `-AutoUpdate compatible\|check\|off` | Between-session update policy |
| `--existing ask\|reuse\|reset` | `-Existing ask\|reuse\|reset` | Existing-installation choice |
| `--activate ask\|shell\|skip` | — | Ask to open a child Bash, open it explicitly, or skip activation |
| `--no-modify-path` | `-NoModifyPath` | Skip PATH registration |
| `--no-codex-integration` | — | Skip Linux Codex package and entry-point setup |
| `CONDA_EXE=/path/to/conda` | `-CondaExe PATH` | Use an existing environment manager |
| — | `-CondaHome PATH` | Select a dedicated Miniforge location |

`reuse` retains the repository transport and automatic-update policy. Branch pins are retained except for the [one-time legacy-to-beta migration](versioning.md). `reset` applies the supplied/default preferences, clears the update-check cache and rebuilds the exact managed PATH registration. Both preserve verified releases and runtime files, project harnesses, unrelated shell/registry settings and modified user content. Reset does not authorize removing unknown directories. Without a terminal, an existing installation requires an explicit choice.

Choose an existing published tag from Releases for `RELEASE_TAG`; the current development branch is source-only.

```bash
curl -fsSL https://github.com/sholee-pt/Harness-Codex/releases/download/RELEASE_TAG/install_harness_codex.sh | sh -s -- --existing reuse
source ~/.bashrc
```

For Windows source development, run from an existing checkout:

```powershell
./installer/install.ps1 -Existing reset
```

## Source installation

```bash
git clone --branch v0.35.1-beta --single-branch https://github.com/sholee-pt/Harness-Codex.git
bash Harness-Codex/installer/install.sh
source ~/.bashrc
```

On Windows, the source installer can be exercised from PowerShell for development: `& ./Harness-Codex/installer/install.ps1` under your normal script execution policy. This does not establish a verified Windows native release. The source scripts install an existing checkout; `install_harness_codex.sh` and `.ps1` first download a release and then invoke the corresponding source installer. Installation does not alter project Git state.

The v0.33.0-beta updater introduces a source-layout contract while retaining the
complete earlier file layout as an upgrade bridge. Later refactors can declare
their current resources and dynamic entrypoints alongside statically checked
imports; an earlier filename is not permanently required just because of its
introduction version. Old immutable receipts retain their existing checks. An
updater predating this bridge cannot interpret a future reduced layout: install
the bridge first, or use the later version's verified release installer. Do not
remove compatibility files in the bridge itself or claim that every older
updater can directly install a future refactored package.

## Path boundaries

Installers validate options and selected tool, command and runtime paths before creating logs, bootstrap locks or environments; public downloaders check their selected paths before downloading. Help remains offline wherever it appears in the argument list. Paths inside Git metadata are refused, including an external parent alias that resolves there. Linux permits external parent aliases but preserves redirected managed roots; Windows refuses reparse points along managed installation paths.

On Linux, an incomplete dedicated runtime can remain after an interrupted setup or an uninstall that preserved unknown files. This includes interrupted Miniforge extraction before the environment or ownership receipt was created. If its ownership marker matches this installation and neither an active installation nor its runtime reference remains, the installer moves the entire old runtime to an adjacent `harness-codex-runtime.recovery.*` directory before preparing a fresh environment. It prints the recovery path and records it in the installation log; retained files and the old ownership receipt are not deleted or claimed by the new install. Keep that recovery copy until you have reviewed its contents. Active installations, unowned directories and redirected runtime paths require inspection instead of automatic recovery. An atomic bootstrap lock directory prevents overlapping installers and is removed on normal exit, failure or Ctrl+C. A power loss or forced kill can leave that lock: confirm no installer is running before removing the empty lock directory named in the diagnostic.

`--project` may name a directory alias, including a symbolic-link home on a shared
Linux server. Harness resolves the selected workspace to its physical directory;
init, config, status, maintenance and removal use that same project. Graft, Jev,
adaptive-routing records and locks also use the physical identity. SSH, VS Code
Remote, MobaXterm and PuTTY connections use this same filesystem rule.

External parent aliases are accepted for goal files, checkpoint/evaluation storage,
plan and receipt outputs, and build locations. The final managed store or output
entry must not be a link. Project-managed `.agents`, `.codex`, `.harness`, generated
instructions and transaction backups retain their no-follow ownership checks;
an alias leading into Git metadata is rejected. Rejected links and their targets
are preserved. If an error identifies one of these managed entries, select an
ordinary project location or inspect that entry before retrying; do not delete
the target merely to bypass the check.

These rules do not expand a project's evidence or writer scopes into linked
external directories. Windows directory junctions are covered by local regression
tests; Windows tool-installation restrictions and its separate release policy
remain unchanged.

## PATH and logs

On Linux, current command wrappers locate their tool installation relative to
the command directory. Owned location fields are bound to that layout at read
time; file hashes and immutable runtime receipts are not replaced simply because
the mount prefix changed. PATH entries and maintenance hook commands under the
account home use `$HOME`. This supports the same home tree mounted at different
absolute prefixes while preserving its relative layout. Custom paths outside
that shared layout remain external paths, and must exist on the selected host.

For an older installation whose command no longer starts after changing servers,
run the current source installer from the new server and choose `reuse`:

```bash
bash Harness-Codex/installer/install.sh --existing reuse
source ~/.bashrc
harness-codex init --project /current/server/path/to/project
```

The installer verifies legacy ownership before repairing command wrappers and
integration. It can reuse the dedicated runtime without executing an obsolete
Conda shebang, but only if that runtime's interpreter and required libraries work
at the new prefix. It does not rewrite Conda binaries or promise compatibility
across operating systems/architectures. A failed ownership or interpreter check
preserves the existing runtime and reports its installation log.

Full `init` replaces only receipt-owned hook commands and verifies their actual
execution before requesting native trust. An existing project harness is retained.
If command repair was interrupted, rerun the installer or use the current source
CLI's `update --repair-launcher --data-dir PATH` from the dedicated Harness
environment. An unknown lock or user modification still requires review.

Codex conversation history can independently retain an obsolete working
directory. Start Codex with `--cd /current/server/path/to/project` before resuming
that conversation. Tool-path repair does not rewrite Codex history or switch a
conversation to a different project's harness.

Linux account homes and installation parent directories may be symbolic links
to shared storage. The installer resolves those external aliases and records
the physical location for reuse and removal. The managed installation root,
runtime root, launcher files, `.bashrc` and credential files must not be links;
their ownership checks still apply. A rejected link is preserved. Use the path
in the error to distinguish a shared-storage alias from a redirected managed file.

The source installer resolves the selected Conda environment and executes its
absolute Python path. It checks the actual Python prefix against the selected
prefix before creating installation state. A conflicting Python earlier on PATH
does not select the interpreter. Expected/actual interpreter details are recorded
in the diagnostic log; parent-shell and project environment settings are preserved.

The Linux installer asks whether to open a new Bash after installation. Enter or yes opens an interactive child shell that reads `~/.bashrc`; `exit` returns to the original shell. This executes your existing Bash startup instructions, including any environment initialization you have configured. It does not modify the parent shell. Choose no to skip. To apply settings in the original Bash, run **`source ~/.bashrc`**, or open a new terminal. Running `~/.bashrc` as a command tries to execute it and may report permission denied; executable permissions are not needed to source it. Use `~/.local/bin/harness-codex --version` to distinguish PATH lookup from command installation. A `bash installer/install.sh` child cannot export variables back into its parent shell. GitHub CLI is not required.

Windows registers user PATH and refreshes the current PowerShell PATH. Other open terminals need restarting. A shared bin directory may remain on PATH after uninstall to preserve other commands.

The installer displays an animated indicator and live elapsed seconds on an interactive terminal, with a detailed log location. It pauses animation while asking for a reinstall choice. Noninteractive/redirected output contains ordinary stage lines; Linux skips child-shell activation when there is no controlling terminal or `--no-modify-path` is selected. Failed downloads, environment setup or installation retain a diagnostic log. Colors are presentation only; redirected output remains readable. An incomplete pre-existing environment is preserved for review instead of being overwritten.

## Ownership and uninstall

Interactive yes/no confirmations use `[Y/n]`: Enter, `y` and `yes` approve; `n` and `no` decline, ignoring capitalization and surrounding spaces. Unknown answers are asked again. Closed input or a noninteractive stream never counts as Enter. This also applies to uninstall, saved-key logout and shell activation. Numbered menus, API-key entry and reuse/reset choices retain their own input rules; existing `--yes` flags remain explicit automation options. `--dry-run` never deletes files.

`update` shows current/latest versions and distinguishes an available update, a completed update and an already-current installation. An unchanged installation does not refresh its Codex integration or print update-completion advice. A failed check exits with an error and does not claim that the installation is current.

The CLI removes only verified files from its own installation. Unowned files, empty directories and unrelated links in tool storage are preserved in place; only receipt-owned files enter removal staging. Pending recovery records and conflicting receipts still stop removal. New dedicated runtime files have immutable SHA-256 ownership receipts. Added or changed runtime files are retained and reported; reused and legacy Conda installations have no inferred ownership and remain installed. Temporary failure logs and other historical untracked files are not deleted by matching their names.

Project harnesses survive tool uninstall. Reinstall, select the same project and run `status`: no global registry is needed because its manifest is stored in the project. Use native `codex` for a compatible harness, update its generator and run `config` when needed, or explicitly `reset`. `remove --include-generator --yes` removes the unchanged owned project installation before tool uninstall if desired. Native Codex history and credentials belong to Codex and remain untouched.

Confirmed uninstall removes the owned saved TypeSafe credential, while preserving project harnesses and Graft/Jev observations. Environment keys are not changed. Unsafe or unrecognized credential storage is preserved and reported. Use `harness-codex jev login` after reinstall to connect TypeSafe again; see [Jev authentication](jev.md#login-and-saved-credentials).

If credential cleanup fails after tool removal, the report identifies that completed step and the preserved credential path (or the unresolved configured directory). No key is printed and ownership checks are not bypassed. Inspect that location and its ownership/permissions; reinstall Harness before using `harness-codex jev logout` for assisted removal.

Owned maintenance hooks and recorded automatic trust changes participate in uninstall rollback. Unchanged trust additions are removed and prior values are restored; user-modified and legacy unrecorded trust stays untouched. Review any preservation warning or recovery-copy location reported by uninstall. See [maintenance ownership](maintenance.md).
