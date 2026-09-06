Harness for Codex v9.2 adds an installed Linux `harness` command, so project setup and everyday work no longer require typing skill names or helper-script paths.

```bash
sha256sum --check SHA256SUMS
tar -xzf harness-9.2-linux.tar.gz
bash harness-9.2/install.sh
export PATH="$HOME/.local/bin:$PATH"
harness --version
harness init --project /path/to/project --goal "Describe your project"
harness start --project /path/to/project
```

- `init` installs the generator and opens native interactive Codex with the appropriate skill selected. `start` opens a working session with the generated project harness selected, including explicit-skill projects.
- `doctor`, `--help`, `--version` and installation dry-runs remain offline. `--install-only` installs without a model call.
- `update --check` inspects numeric Codex version branches. Managed installations check once per day before interactive sessions and apply same-major forward updates by default. Choose `--auto-update check` or `off` during installation, or `--no-update-check` for one session. Major upgrades require explicit update.
- Tool releases use separate user-local storage, file integrity receipts and atomic activation. Upstream operations never change project Git metadata or automatically regenerate project artifacts. Existing user files and edited managed files remain protected.
- Existing v9.0/v9.1 artifacts and all project schemas remain compatible. The original installer and direct skill invocation remain supported.

Anaconda or Miniconda and an authenticated Codex CLI are prerequisites. The installer prepares the dedicated `harness` Python environment; the archive is not a bundled model or Codex binary. Private-repository downloads and updates require existing GitHub access. Codex's model, sandbox, approval and hook-trust settings remain in effect.

Release publication is gated on Linux and Windows validation, including previous-release upgrades, CLI tests, the pinned parser oracle and a real Linux archive/bootstrap/launcher check. CLI dispatch tests use a controlled fake Codex process; these checks do not establish live model quality, agent discovery success, token savings or a hard Git authorization gate.
