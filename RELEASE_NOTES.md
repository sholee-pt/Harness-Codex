Harness for Codex v9.4 adds project-description files and explicit project lifecycle commands.

- Supply a Markdown brief with `harness init --project PATH --goal-file brief.md`. `--goal` remains available for short text; both describe the project for source-grounded analysis, not the initial task of `start`.
- Use `--agent codex` as the provider selector. `--runtime` remains a hidden compatibility alias, with conflicting choices rejected. Claude integration is not implemented.
- Plain `init` reports an existing project harness without launching Codex. Use `configure`, an explicit goal on `init`, or `reset` when changes are intended.
- `harness status --project PATH` reports generator and generated-harness state separately.
- `remove` and `reset` preview by default; add `--yes` to apply. Removal preserves user files, checks managed hashes, and offers journaled recovery through `remove --recover`. `--include-generator` also removes unchanged installer-owned files.
- Existing v9.0–v9.3 generated projects remain compatible. The CLI removal journal has its own operation/version and is not a generator Schema 2 transaction.

```bash
harness init --agent codex --project /path/to/project --goal-file /path/to/project-brief.md
harness start --agent codex --project /path/to/project
harness status --project /path/to/project
harness reset --project /path/to/project --goal-file /path/to/project-brief.md --yes
```

Private authenticated bootstrap installation remains available through `install_harness.sh`; Git, tar and Conda are prerequisites, and Codex CLI requires its own installation/authentication. Linux/Windows tests, real old-version upgrades and bootstrap checks gate publication. Installation checks do not establish live agent quality or token savings.
