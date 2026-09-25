# Harness Repository Instructions

## Scope

- This branch contains Harness for Codex v0.23.0-beta, a project-local workspace harness generator with safe project-local generator installation, user-selected folder boundaries independent of Git layout, strict frontmatter and agent contracts, Manifest Schema 7 / Artifact Contract 2, and deterministic runtime contracts.
- Keep generated project artifacts native to Codex: `.codex/agents/`, `.agents/skills/`, `AGENTS.md`, and `.harness/manifest.json`.
- Do not add telemetry or marketplace dependencies. The separately authorized CLI distribution layer may check/fetch this repository and publish verified GitHub release assets; project generation never performs those operations.
- Keep general task evaluation default-off, user-local, and isolated from generation/apply failure handling. The owner-authorized init default may enable bounded Jev shadow advice and its local counters after Graft is ready and preserves explicit opt-outs. Only explicit new-key entry permits a fixed, bounded non-project authentication probe; existing credentials never trigger an init API call. Store credentials separately from project artifacts, metrics and shell profiles.
- Keep operations evidence opt-in, enum-only, user-local, and outside generated project artifacts. Never retain raw prompts, responses, transcripts, agent names, or absolute paths.
- Preserve the proprietary license and independently authored implementation.

## Skill maintenance

- Treat `.agents/skills/harness/SKILL.md` as the concise router.
- Put conditional design guidance in `references/`, deterministic helpers in `scripts/`, and output templates in `assets/`.
- Generate agents and project skills only when workspace evidence justifies them.
- Accept plain directories, Git-contained folders, linked worktrees, and multi-repository workspaces. Respect the selected root; Git boundaries are analysis context, not a root-selection gate.
- Never inspect or mutate Git remotes, credentials, branches, commits, pushes, pull requests, or deployments during generation.
- Do not modify Git metadata during generator installation or project generation. Preserve user-owned instructions and files through explicit ownership and hash checks. Generated files are not automatically ignored or untracked.
- Preserve user-owned content and test idempotent updates.
- Keep current-task roles, plans, messages, adapter selection, and retention out of the persistent manifest.

## Validation

- Run every Python command inside the Anaconda environment named `harness`; prefer `conda run -n harness python ...` so the environment is explicit.
- Never use the base Anaconda environment or an unrelated bundled Python for Harness maintenance.
- After any repository modification, run a lightweight fixture dry-run before broader tests and include the dry-run result in the completion report.
- Run `conda run -n harness python -m unittest discover -s test -v`.
- Run runtime-plan fixture validation when teamplay code or contracts change.
- Run the system skill validator against `.agents/skills/harness` when available.
- Report any validation that could not be executed.

## Git conventions

- After dispatching GitHub Actions, report the workflow link and stop. Do not poll, watch, schedule monitoring, or wait for completion unless the owner explicitly asks for another status check. The owner checks release progress directly.
- Determine runtime Codex compatibility from available capabilities and validated event shapes, not a version allowlist. Keep the reviewed native build revision as reproducibility metadata, separate from runtime compatibility.
- New Codex branches use `vX.Y.Z-beta` during development: X for major or large-scale changes; Y for minor features, improvements, refactoring and optimization; Z for bug fixes (`[Fix]`). Preserve legacy versions in immutable receipts and compatibility tests.
- Historical display versions map `vN.M` to `v0.N.M-beta`; this is a label correction, not a claim that old source was rebuilt. This repository contains the Codex edition only.
- Public stable releases begin at `v1.0.0` after an explicit release decision; repository visibility alone does not publish a release.
- Use `[Doc]` for explanatory documentation-only changes that do not affect harness generation or runtime behavior, and do not increment the version for them. Generator instructions, templates and contracts are behavioral inputs even when written in Markdown; classify their changes by effect, not file extension.
- Other commits use `[Feat]`, `[Fix]`, `[Refactor]`, `[Test]`, or `[Chore]`. Choose the version increment by the change's effect; refactoring and optimization use Y, not Z. See `docs/versioning.md`.
- Do not commit, push, merge, or rewrite history unless the user has authorized it. An explicit implementation request from this repository owner includes commit and push. Keep the latest development version as the default branch and retain only that version branch, as authorized by the owner. Branch updates do not establish release verification; publish release assets only after the required checks pass. This repository-maintenance convention does not authorize remote operations during generated-project configuration.

## CLI distribution

- Keep the Linux/Windows command and updater separate from native project generation. Upstream fetches use only tool-owned storage and never inspect project remotes or reset project Git state.
- Preserve native Codex model, sandbox, permission, and hook-trust settings by default. The explicitly authorized configuration picker may pass the user's selected model, reasoning and permissions for that native conversation; never persist global overrides or retry a rejected choice with broader permissions. CLI convenience is not an approval bypass or an independent agent engine.
- Keep help, version, doctor, and dry-run offline. Updates occur between sessions and preserve edits in managed installations.
- Harness owns project management; native `codex` owns conversations. Use the pinned native Codex executable directly, without a Harness work-session launcher or bootstrap user turn. Treat per-request model/effort selection as explicit inference policy rather than permission changes. Do not add a separate routing model, persist raw routing transcripts, or claim measured cost/quality benefits from deterministic routing tests.
- The owner's exact-UI requirement supersedes the separate terminal renderer: use a pinned upstream Codex CLI build with a bounded Auto-menu/inference extension. Preserve its original renderer, theme, input handling and permission code. Keep third-party license/notice material separate from the proprietary Harness generator. Windows builds, platform validation and release assets are paused until the owner explicitly requests them. Publish Linux assets only after the Linux native build, original TUI/extension tests and integration checks pass; retained Windows source is not a validated Windows release.
