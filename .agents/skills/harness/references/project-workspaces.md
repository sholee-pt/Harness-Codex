# Selected Project Folders

Read this reference before analyzing or applying a project harness. v9.5 uses a project-local contract without automatic Git exclusion.

## Workspace classification

The user's selected folder is the generation and ownership root. Supported contexts include `plain-directory`, `directory-workspace`, `git-repository`, `git-worktree`, and `git-contained-directory`. A selected folder may contain registered submodules, independent repositories, or linked worktrees. GitHub hosting and Git remotes are irrelevant to generation.

Known Git boundaries inform responsibility analysis. They do not automatically establish separate ownership or prohibit a scoped writer. Multiple repositories can participate in one selected project when the user's task and declared scopes justify it. Every managed output, evidence path, and writer scope must remain inside the selected root; symlink and junction escapes are refused.

Inventory Schema 5 and Root Context Schema 3 report bounded scan coverage. Content exclusions and Git-boundary observations remain distinct. Truncated or unreadable paths remain unknown, without requiring the user to move the project or inferring that no boundary exists.

## Project-local application

Manifest Schema 7 / Artifact Contract 2 records `scope: project-local` and `gitProtection: {"mode": "not-managed", "patterns": []}` in every supported workspace kind. Installation and generation perform no GitHub request, remote inspection, Git metadata write, staging, commit, push, branch change, or deployment.

Harness does not add ignore rules or require a single registered worktree. Generated files may be visible in Git status or tracked by the user. File ownership and recorded hashes govern safe updates; tracking is not ownership. Existing exclusion blocks from earlier releases remain byte-identical and are neither adopted nor deleted during upgrade. The user's Git policy remains separate from generation.

## Generator and generated artifacts

Run the source checkout's `conda run -n harness python install.py --root TARGET --dry-run`, then the same command without `--dry-run`. The root must already exist. The generator is installed inside `TARGET/.agents/skills/harness`; its `.harness-install.json` receipt owns only that generator's files. Nonempty unmanaged destinations and modified managed files are refused. Updates preserve other files and use a staged directory with backup restoration on a failed rename. The installer does not modify the project's `.harness/manifest.json`.

Calling `$harness` creates or updates the separate project router, justified agents and skills, and `.harness/manifest.json` inside the selected root. Calling `$project-harness` uses those artifacts for project work. An explicit home-folder root supports user-level generator installation; home installation is not required.

v9.5 installer updates preserve the existing generator folder's POSIX mode and modification time, plus retained subdirectory modes. Newly copied directories use source modes; a fresh generator root uses the source root's mode. Contents are prepared before restrictive directory modes are applied. A changed destination root during preparation is refused. Windows ACLs, extended ACLs, ownership and extended attributes are outside this mode-preservation claim. Use the new source checkout's `install.py` for the installer fix; generator installation and project-artifact updates are separate operations.

Git-tracked project files remain editable within a requested task. Commit, push and destructive Git actions follow the user's scoped authorization; see [git-authorization.md](git-authorization.md). Static scope validation and generated advice are not command or API interception.

## Existing project instructions

- If the active root instruction path is absent, Harness may create a managed pointer.
- If a clean manifest already owns its marker block, Harness may update that block while preserving surrounding user content.
- Otherwise preserve user-owned instructions byte-for-byte and record `explicit-skill` activation; invoke `$project-harness` explicitly.
- Do not create an override merely to bypass existing project guidance.

Codex builds root guidance when a run starts. If a new pointer, skill, or custom agent is not visible, start one fresh task in the same selected folder; do not restart after each request.

## Optional evaluation boundary

The clone-based paired evaluator has a separate Git-root and isolation contract; see [evaluation-isolation.md](evaluation-isolation.md). Those evaluation preconditions do not restrict generator installation, project generation, or ordinary use of a generated harness.
