# Local-only Workspaces

Read this reference before selecting a root or applying generated artifacts.

## Workspace classification

- `plain-directory`: a non-Git project directory with no nested Git boundary.
- `directory-workspace`: a non-Git directory containing one or more nested Git boundaries. Harness may analyze the outer workspace while treating each nested repository as a boundary.
- `git-repository`: a local Git work-tree root whose `.git` marker is a directory.
- `git-worktree`: a local linked work-tree root whose `.git` marker is a file.
- `git-contained-directory`: a directory below a Git root. Select the actual Git root or a directory outside that work tree before applying a harness.
- `scan-incomplete`: the root scan exceeded its bound or could not read a directory. Do not infer that unscanned paths contain no Git boundary.

Registered submodules are allowed inside a Git root. An independent or linked nested repository makes a Git root ambiguous and requires a narrower selection. The same nested repositories are valid boundaries inside a non-Git `directory-workspace`.

An outer directory-workspace harness may read and route across nested boundaries, but persistent writer scopes may not enter an independent nested repository. Select that repository as the root for code-changing work. This avoids silently treating unrelated Git histories as one write transaction.

File-inventory exclusions and root-boundary exclusions are intentionally separate. Dependency, vendor, output, data, and checkpoint directories may be omitted from content classification, but the root scan still checks them for `.git` markers. The inventory reports scanned, truncated, unknown, and policy-excluded coverage explicitly.

## Local-only application

Harness performs no GitHub API request and no Git remote inspection. It does not stage, commit, push, open a pull request, or change a branch.

For `git-repository` and `git-worktree` roots, apply uses only local Git metadata:

1. Read `git worktree list --porcelain -z` and require exactly one registered worktree. The common `info/exclude` file is shared by the main and linked worktrees, so any count above one is rejected regardless of which worktree is selected.
2. Refuse any planned Harness target that is already tracked.
3. Reject generated path components containing C0 controls or DEL. Encode Git ignore metacharacters, including spaces, as literal path characters instead of broadening the match.
4. Add the exact encoded generated paths and `/.harness/` to a marker-owned block in the local `info/exclude` file before writing project artifacts.
5. Preserve every byte outside that block, including the existing newline form and file mode.
6. Recheck the worktree count, tracking state, and exclude-file drift immediately before apply.

The local exclude reduces accidental inclusion but cannot prevent a user from force-adding a path manually. Report this limitation accurately.

If project application fails synchronously before a transaction is pending, Harness conditionally restores the original exclusion file. Restoration occurs only when the current file is exactly the block Harness just wrote; an external edit, a pending recovery journal, or an uncertain transaction state stops automatic restoration and requires explicit recovery. This compensation does not cover abrupt process termination between the exclusion write and transaction-journal creation.

A Harness-owned marker block without a matching manifest is unbound state. The builder and installed-state validator report it instead of silently adopting or deleting it. Inspect the shared Git metadata and remove the block explicitly only after confirming that no installation or pending recovery depends on it.

For plain directories, Git protection is `not-applicable`; generated files still remain only in that local directory.

## Existing project instructions

- If the active root instruction path is absent, Harness may create a local managed pointer and exclude it in a Git workspace.
- If its marker block is already owned by a clean manifest, Harness may update only that block, provided the file is not tracked.
- If an existing instruction file is user-owned or tracked, preserve it byte-for-byte. Record `explicit-skill` activation and tell the user to invoke `$project-harness` when needed.
- Never create `AGENTS.override.md` merely to bypass a tracked `AGENTS.md`; that could suppress the user's active instructions.

Codex detects local skill changes automatically. `AGENTS.md` guidance is assembled when a run starts, so a newly created pointer applies on a fresh task. If new custom agents or skills are not visible, start one fresh task in the same workspace; do not delete the old task and do not restart for every question.
