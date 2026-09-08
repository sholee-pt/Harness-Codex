Harness for Codex v9.8

Adds a native Windows PowerShell installer and reproducible Windows ZIP alongside the Linux installer. Both platforms use `harness-codex`; `config` remains the public configuration command.

## One-command Linux installation

For public release access, run:

```bash
curl -fsSL https://github.com/sholee-pt/Harness/releases/download/codex-v9.8/install_harness_codex.sh | sh
```

The standalone script verifies the release archive's SHA-256, reuses an existing Conda installation or installs checksum-pinned [Miniforge 26.5.3-0](https://github.com/conda-forge/miniforge/releases/tag/26.5.3-0), creates the dedicated `harness` Python environment, installs `harness-codex`, and registers its bin directory in `~/.bashrc`. No sudo or GitHub CLI is required. Linux x86_64 and aarch64 are supported for environment setup. The machine needs curl, Bash, tar and sha256sum; the installer explains missing system utilities before installation. Git is included in a newly created environment for subsequent updates.

Open a new terminal, or apply the registration once in the current terminal:

```bash
. ~/.bashrc
harness-codex --version
harness-codex --help
```

A child process started by `curl | sh` cannot change its parent shell's environment. Registration makes the command available in fresh Bash sessions. Existing matching PATH exports are kept, repeated setup adds no duplicate export or PATH entry, and unchanged profiles retain their bytes and modification time. An edited Harness PATH block or a linked startup file is preserved with an explanation. Use `--no-modify-path` for manual PATH management. Installation does not initialize Conda or activate it in the project shell.

GitHub `/blob/` URLs return an HTML page, not executable script content. Use the Release asset URL above or a `raw.githubusercontent.com` script URL.

Public deployment support does not change the repository's visibility. While this repository is private, anonymous curl downloads cannot access it. The existing authenticated source installer remains available:

```bash
git clone --branch codex/v9.8 --single-branch git@github.com:sholee-pt/Harness.git Harness
bash Harness/install.sh
```

The advanced `install_harness.sh` bootstrap still supports existing HTTPS credentials, tokens and SSH transport for branch selection. It delegates to the same source installer and environment preparation. Git author name/email are not authentication. Codex CLI installation and login remain prerequisites for actual Codex sessions; version/help, installation and diagnosis do not require a model call.

## One-command Windows installation

In a 64-bit Windows PowerShell 5.1 or PowerShell 7 terminal, for public release access:

```powershell
irm https://github.com/sholee-pt/Harness/releases/download/codex-v9.8/install_harness_codex.ps1 | iex
harness-codex --version
harness-codex --help
```

The PowerShell installer verifies the Windows ZIP checksum and entry paths before extraction, reuses Conda or downloads the pinned official Windows x64 Miniforge installer, prepares the `harness` Python 3.11 environment, and installs `harness-codex.cmd`. It registers the bin directory in **HKCU\Environment\Path** and adds it to the current PowerShell session. Existing entries and registry string type are preserved; repeated registration adds no duplicate. No administrator, GitHub CLI, PowerShell profile change, persistent execution-policy change, or system PATH change is required. Codex CLI itself still needs to be installed and authenticated for project sessions.

Default tool storage is `%LOCALAPPDATA%\HarnessCodex`; commands live in `%LOCALAPPDATA%\Programs\HarnessCodex\bin`. The optional Miniforge fallback uses `%LOCALAPPDATA%\HarnessCodexConda`. New terminal windows load the registered user PATH. A script launched in a separate child PowerShell cannot change its parent terminal; reopen the terminal in that case. WSL uses the Linux installer. Windows ARM64 and 32-bit PowerShell are not supported by this installer.

To choose installation paths or manage PATH yourself, download the script and invoke its reviewed contents with options:

```powershell
& ([scriptblock]::Create((Get-Content ./install_harness_codex.ps1 -Raw))) -BinDir 'D:\Tools\HarnessCodex\bin' -DataDir 'D:\Tools\HarnessCodex\data' -NoModifyPath
```

`-CondaExe PATH` selects an existing Conda executable; `-CondaHome PATH` selects a dedicated Miniforge prefix. Existing unrelated/incomplete directories are preserved and reported. Miniforge downloading has a 300-second request timeout and its native installer has a 600-second process limit. Conda dependency resolution/download has no overall deadline. A failed Miniforge installation leaves its partial prefix for inspection instead of deleting unknown files.

While the repository is private, the public Windows URL has the same authentication limitation as Linux. With working GitHub SSH authentication:

```powershell
git clone --branch codex/v9.8 --single-branch git@github.com:sholee-pt/Harness.git Harness
& ([scriptblock]::Create((Get-Content ./Harness/install.ps1 -Raw))) -SourceRoot (Resolve-Path ./Harness).Path
```

## Start a project

```text
harness-codex init --project "PROJECT_PATH" --goal-file "PROJECT_BRIEF.md"
harness-codex start --project "PROJECT_PATH"
harness-codex config --project "PROJECT_PATH"
```

`init --install-only` installs the project generator without starting Codex. Installed `init` also restores missing user PATH registration on either platform; `--dry-run` does not write it. Existing project files and Git metadata retain the same ownership and authorization checks. Tool installation does not install Codex itself, log into a provider, or install project/model dependencies.

## Updates and compatibility

- Existing named v9.7 installations can use `harness-codex update`. Old v9.2–v9.6 generic `harness` installations keep their recorded command and paths when updated. The fresh installer uses the Codex-specific command by default.
- Use `harness-codex init --project PATH --install-only`, then `harness-codex config --project PATH`, to separately adopt new project generator guidance.
- Windows updates can find Git in the dedicated Conda environment even when the project shell's PATH contains no Git. This adjusts only the Git child process; project/Codex environment variables remain inherited from the caller.
- Authoring Contract 3, Plan Schema 3, Manifest Schema 7 and Artifact Contract 2 are unchanged. Valid v9.0–v9.8 project artifacts remain accepted.
- Missing v9.8 Windows PATH runtime code is rejected before installation state is created. Root bootstrap scripts remain optional for updates made by old source allowlists.

## Release files

[The latest Codex Release](https://github.com/sholee-pt/Harness/releases/tag/codex-v9.8) contains:

| File | Purpose |
| --- | --- |
| `install_harness_codex.sh` | Standalone public `curl | sh` installer, pinned to this release |
| `install_harness_codex.ps1` | Standalone Windows PowerShell installer, pinned to this release |
| `harness-codex-9.8-linux.tar.gz` | Tool source and offline installation entry point; no bundled model or Codex binary |
| `harness-codex-9.8-windows.zip` | Same runtime payload in ZIP format, with `install.ps1` |
| `SHA256SUMS` | SHA-256 for both archives and both standalone installers |
| `build.json` | Version, immutable source commit and build hashes |

After downloading the Linux archive and `SHA256SUMS`, manual installation is:

```bash
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf harness-codex-9.8-linux.tar.gz
bash harness-codex-9.8/install.sh
```

Only the latest GitHub Release is retained under the owner's distribution policy. Version-control tags and commits remain available for reproducibility; deleted older Release asset URLs are no longer installation endpoints.

## Validation scope

Publication requires Linux and Windows full regression tests, immutable v7.6–v9.7 source upgrade checks, release builds, and actual installed-command checks. Windows PowerShell 5.1 CI exercises a fresh Miniforge installation, a new harness environment, the `.cmd` launcher, real user registry PATH registration, repeated installation with preserved bytes/mtime, offline `init`, and bundled Git discovery. Linux CI retains its real cold Miniforge/Bash installation check. Local Windows PowerShell 7 also exercises existing-Conda installation without changing the user's persistent PATH.

The public Harness URLs are replaced with exact built assets in bootstrap integration checks because this repository is private. Official Miniforge HTTPS downloads and pinned checksum verification are real; authenticated published-asset downloads are verified separately. This does not establish anonymous access to a private repository. Windows ARM64/32-bit, Linux ARM64 execution, live native agent loading, GPU training, model quality and token savings are not claimed by these checks. Prior Windows regression coverage did not include the Windows bootstrap introduced here.
