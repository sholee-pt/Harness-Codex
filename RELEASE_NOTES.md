Harness for Codex v9.3 adds a downloadable Linux bootstrap and explicit runtime selection while retaining v9.0/v9.1/v9.2 project compatibility.

- Download `install_harness.sh` using authenticated curl or the signed-in release page, then run `bash install_harness.sh --runtime codex`. GitHub CLI and manually unpacking a release archive are not required.
- The bootstrap selects only numeric Codex version branches, fetches an immutable source commit into temporary tool storage, validates the tree, and invokes the safe installer. Linux requires Git, tar and Anaconda/Miniconda; the dedicated `harness` environment is created if absent.
- Private access uses an existing Git credential provider, SSH key, or `GITHUB_TOKEN`/`GH_TOKEN`. `git config user.name` and `user.email` are author metadata, not authentication. The initial private curl download needs a real HTTPS credential too; an SSH-only setup uses the documented Git download route.
- `harness --runtime codex ...` is supported. Claude integration is planned as a separate adapter/channel under the same command. `--runtime claude` explicitly exits before preparation or changes; this release does not implement Claude execution.
- Codex archives are named `harness-codex-9.3-linux.tar.gz`. The standalone script, checksums and source-bound build metadata are attached. Project schemas, Codex storage and old metadata remain compatible.

After installation:

```bash
export PATH="$HOME/.local/bin:$PATH"
harness init --project /path/to/project --goal "Describe your work"
harness start --project /path/to/project
harness update --check
```

Codex CLI must be installed and authenticated separately. Native permission/model settings remain in effect. Publication is gated by Linux/Windows tests, previous artifact and CLI upgrades, the parser oracle, package installation and the real authenticated bootstrap. These checks do not prove live agent quality, token savings, or a hard Git authorization gate.
