Harness for Codex v9.7

## One-command Linux installation

For public release access, run:

```bash
curl -fsSL https://github.com/sholee-pt/Harness/releases/download/codex-v9.7/install_harness_codex.sh | sh
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
git clone --branch codex/v9.7 --single-branch git@github.com:sholee-pt/Harness.git Harness
bash Harness/install.sh
```

The advanced `install_harness.sh` bootstrap still supports existing HTTPS credentials, tokens and SSH transport for branch selection. It delegates to the same source installer and environment preparation. Git author name/email are not authentication. Codex CLI installation and login remain prerequisites for actual Codex sessions; version/help, installation and diagnosis do not require a model call.


## Changes and compatibility

- The command is `harness-codex`; `config` is the primary project configuration command and `configure` remains an alias.
- Fresh installs use Codex-specific tool storage. Existing generic installations preserve their recorded names and remain updateable.
- Installation and installed `init` register Bash PATH without duplicate exports or repeated writes. Existing profile content and permissions are preserved. `--no-modify-path` opts out during installation.
- A missing Conda installation is supplied through a pinned, hash-verified Miniforge installer. Project shell activation and Codex configuration remain native.
- Reinstalling identical tool state avoids rewriting its active pointer. Redundant CI runs of tests already covered by full discovery were removed. Safety, compatibility and installed-command checks remain.
- Authoring Contract 3, Plan Schema 3, Manifest Schema 7 and Artifact Contract 2 are unchanged; valid v9.0–v9.7 project artifacts are accepted.

## Release files

[The latest Codex Release](https://github.com/sholee-pt/Harness/releases/tag/codex-v9.7) contains:

| File | Purpose |
| --- | --- |
| `install_harness_codex.sh` | Standalone public `curl | sh` installer, pinned to this release |
| `harness-codex-9.7-linux.tar.gz` | Tool source and offline installation entry point; no bundled model or Codex binary |
| `SHA256SUMS` | SHA-256 for the archive and standalone installer |
| `build.json` | Version, immutable source commit and build hashes |

After downloading all three named input files, manual installation is:

```bash
sha256sum --check SHA256SUMS
tar -xzf harness-codex-9.7-linux.tar.gz
bash harness-codex-9.7/install.sh
```

Only the latest GitHub Release is retained under the owner's distribution policy. Version-control tags and commits remain available for reproducibility; deleted older Release asset URLs are no longer installation endpoints.


## Validation scope

Linux and Windows regression tests, real prior-version source upgrades and installed-command tests gate publication. The cold Linux pipeline test uses exact locally built Harness assets in place of this currently private repository's public URLs; Miniforge download, checksum verification, Conda creation, Bash startup discovery and repeated installation are real. Authenticated GitHub installation and published asset hashes are checked separately. This does not establish anonymous access while the repository remains private, native reviewer completion, model performance improvement or token savings.
