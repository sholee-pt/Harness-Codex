# Project harness architecture

## What It Generates

```text
target-project/
├── .codex/agents/                 # Project-specific custom agents, when justified
├── .agents/skills/
│   ├── harness/                   # Installed generator and its separate installation receipt
│   ├── project-harness/           # Project orchestration skill
│   └── <project-skill>/           # Reusable project procedures, when justified
├── .harness/manifest.json         # Ownership, topology, and content hashes
├── .harness/transaction.json      # Present only while recovery or cleanup is required
└── AGENTS.md or AGENTS.override.md # Optional local pointer when the path is safe to manage
```

Simple projects may receive only `project-harness`. Harness does not create a fixed team or assume a frontend/backend architecture. It classifies persistent project topology independently from the execution complexity of any one task.


## Original generator-only installation

Install the generator in the folder you selected for the project. GitHub membership, Git-root alignment, nested repositories, and registered worktree count do not determine whether that folder can host a harness. The target folder must already exist. Anaconda or Miniconda provides the dedicated standard-library-only Python environment.

```shell
git clone --branch codex/v9.9 --single-branch https://github.com/sholee-pt/Harness.git Harness
conda env create --file Harness/environment.yml
conda run -n harness python Harness/install.py --root "TARGET_PROJECT" --dry-run
conda run -n harness python Harness/install.py --root "TARGET_PROJECT"
```

Replace `TARGET_PROJECT` with the project folder's path. The same commands work in PowerShell, macOS, and Linux shells. If the environment already exists, use `conda env update --name harness --file Harness/environment.yml` instead of creating it again. A downloaded source archive also works; Git is only needed for the clone command.

The installer copies `SKILL.md`, scripts, references, and assets into `TARGET_PROJECT/.agents/skills/harness`. It records its file hashes in that generator folder's `.harness-install.json`, separately from the generated project's `.harness/manifest.json`. It does not install Codex CLI or project dependencies. Keep the source checkout to run later installer updates.

Reinstalling unchanged content performs no writes. Updates preserve unmanaged files, refuse modified managed files and unmanaged path collisions, and roll back a failed folder promotion. A nonempty destination without an installer receipt is never adopted, even when its files match: preserve a previous manual copy elsewhere before installing into an empty destination. Installing into the source checkout itself is a receipt-free no-op. Symlink and junction paths, and target roots inside `.git` metadata, are refused.

On POSIX, updates preserve the existing generator folder's mode and modification time and the modes of retained directories. New directories use their source modes; a new installation uses the source generator folder's mode. Permissions are finalized after staging the contents. This does not promise preservation of Windows ACLs, extended ACLs, ownership, or extended attributes. If a previous v9.0 update already changed directory modes, updating preserves those current modes; it cannot reconstruct the original intended permissions. Review affected directories against known prior settings rather than applying a blanket chmod. Run updates with the new release's `install.py` from its source checkout; the installed generator payload does not include this bootstrap installer.

The installer reports new directories separately as `directoriesCreated`. An update containing only new empty directories can have zero file `writes` and still perform an update. Repeating that installation is a true no-op.

For an explicitly chosen user-level installation, pass your home folder as `--root` (for example `--root "$HOME"`); the resulting destination is `$HOME/.agents/skills/harness`. No home location is selected automatically. If a newly installed skill is not visible, start one fresh Codex task in the target folder.


## Usage

Open the target project directory in Codex and run:

```text
$harness configure a project harness inside this selected workspace.
```

The skill also recognizes direct requests such as “configure the harness” and “하네스를 구성해줘”. Run the same command later to audit or update an existing generated harness.

Harness first creates a structured proposal and runs a no-write dry-run. It applies files only when all ownership, selected-folder path safety, and instruction-precedence checks pass. Changed outputs are staged with backups before a journaled apply, and the manifest is written last. Codex detects skill changes automatically. A newly created `AGENTS.md` pointer applies on a fresh run; if a new custom agent or skill is not visible, start one new task in the same directory. No task deletion or per-request restart is required.

Harness for Codex v9.9 retains a strict shared skill-frontmatter parser and binds every generated agent's instruction contract to its structured topology. It does not ask the model to reproduce fixed change-discipline or runtime-teamplay contracts. Authoring Contract 3 drafts use path-specific placeholders, and `harness_plan_builder.py` deterministically materializes a normal Schema 3 plan before the existing apply validator runs. Every project router and generated agent receives its required canonical block exactly once; an old draft revision, unsafe output path, or missing, duplicate, or misplaced placeholder fails before any workspace write.

The installed skill includes `references/minimal-draft-plan.json`, so plan authoring does not depend on repository-only test fixtures.


## Activation Diagnostics

After generation, run the read-only diagnostic when installation or activation is unclear:

```shell
conda run -n harness python TARGET_PROJECT/.agents/skills/harness/scripts/harness_doctor.py --root TARGET_WORKSPACE
```

The report checks the dedicated environment and installed-state validation, then distinguishes `managed-pointer` from `explicit-skill` activation. `configured` means the files and activation contract validate; `runtimeLoaded: not-tested` means live loading has not been observed. A missing Codex CLI does not invalidate a desktop installation. The diagnostic never launches Codex, installs hooks, or repairs files. Use the mode-aware [live smoke test](../.agents/skills/harness/references/codex-smoke-test.md) when actual discovery or delegation must be observed.

For a small direct task, the generated router keeps scope, expected output, and verification in the current task. It does not require a separate runtime-plan file, coordination packet, relay receipt, or disposable capability probe. Explicit planning requests and required quality checks still apply. If the task later needs delegation, validate the ephemeral plan before spawning. The canonical runtime contract remains unchanged; this is a reduction of unnecessary task artifacts, not a measured token-saving claim.


## Selected Project Folders

Harness accepts plain folders, Git roots, Git-contained subfolders, linked worktrees, and folders containing multiple repositories. Git boundaries are context for analyzing responsibilities; they do not replace the user's selected project root or automatically prohibit a scoped writer inside a nested repository. Write scopes and evidence must remain inside the selected folder, and symlink or junction escapes remain rejected.

Generation does not query GitHub or remotes and does not modify Git metadata, exclusions, the index, commits, branches, or deployment settings. Generated files may appear in Git status and may be tracked if the user chooses. Harness neither guarantees that they remain ignored nor changes existing user or legacy exclusion rules. File ownership and recorded hashes govern safe updates independently of Git tracking.

For later project work, requested source edits and tests remain allowed within scope. Commit and push each need authorization covering that operation; commit approval alone does not authorize push. Force push, history rewriting, branch deletion, and discarding work need approval covering that destructive action. Existing approval remains usable only for its authorized repository, work, and destination. New routers and agents receive this advice without a new required artifact block. Harness does not intercept shell commands or API calls: strict enforcement depends on the actual executor's permission controls. See [Git authorization policy](../.agents/skills/harness/references/git-authorization.md).

Inventory Schema 5 and Root Context Schema 3 report known Git boundaries and bounded scan coverage. Truncated or unreadable coverage is an uncertainty to report, not proof of absent boundaries or a demand to move the selected root. Existing user-owned instructions remain unchanged and select `explicit-skill` activation; invoke `$project-harness` directly. Harness never creates an override merely to bypass existing project guidance.


## Runtime Teamplay

Harness for Codex v9.9 keeps persistent workspace topology separate from current-task execution. It creates no permanent team merely because multiple agents exist. A temporary runtime plan selects `direct`, `delegated`, or `coordinated` execution from interaction value: independent work delegates, one review pass uses delegated producer-reviewer, and only repeated feedback, conflicting expert judgment, cross-boundary agreement, or dynamic reassignment justifies coordination.

Runtime plans are bound to the exact manifest and canonical topology, validated before execution, and ephemeral by default. Their `participants` are the persistent agents activated for the current task. For delegated or coordinated work, Codex is instructed to spawn only those custom agents, collect parent-facing coordination packets, relay material evidence to affected agents, and keep final integration and task state under parent control. Parallel delegation uses `codex-subagent-relay`; unavailable delegation falls back to sequential relay or direct execution while preserving input, output, and verification contracts. Runtime roles and task state are never inserted into the persistent manifest.

```shell
conda run -n harness python .agents/skills/harness/scripts/validate_runtime_plan.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json

conda run -n harness python .agents/skills/harness/scripts/validate_coordination_packet.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --packet COORDINATION_PACKET.json

conda run -n harness python .agents/skills/harness/scripts/harness_relay_receipt.py \
  --root TARGET_REPOSITORY \
  --plan RUNTIME_PLAN.json \
  --receipt RELAY_RECEIPT.json
```

See [teamplay-contract.md](../.agents/skills/harness/references/teamplay-contract.md), [runtime-plan.md](../.agents/skills/harness/references/runtime-plan.md), [native-subagent-relay.md](../.agents/skills/harness/references/native-subagent-relay.md), [runtime-observation.md](../.agents/skills/harness/references/runtime-observation.md), [relay-receipt.md](../.agents/skills/harness/references/relay-receipt.md), and [team-recipes.md](../.agents/skills/harness/references/team-recipes.md). v9.9 keeps Codex as the execution engine while using canonical receiver handles for bounded control, optional versioned public/local observation profiles for evidence, required-task accounting, and hash-bound offline review lineage. Capability policies use a small canonical registry so validated names cannot silently select a different fallback path. Missing observation evidence lowers confidence without cancelling a valid handle execution; verified binding or terminal-outcome contradictions fail closed.


## Design Rules

- Workspace evidence determines roles, skills, and orchestration. Every evidence claim is bound to an existing file hash and may identify an exact line range.
- Persistent material boundaries record topology-wide unique decision-area IDs, project persistence, contracts, verification, failure impact, and separation benefits.
- Project topology is `minimal`, `modular`, or `coordinated`. Boundary count alone does not force coordination; recurring workspace-level coordination does.
- Current tasks are routed independently as `direct`, `delegated`, or `coordinated`. One-off task risk is never persisted as project topology.
- Runtime coordination is selected from repeated interaction value, not agent count, repository size, or simple parallelism.
- Runtime roles, tasks, messages, adapter choice, and retention live only in a manifest-bound ephemeral plan.
- Six collaboration patterns are available as design vocabulary, not mandatory templates.
- Quality patterns are separate policies with workspace evidence, finite budgets, stopping conditions, and failure handling.
- Concurrent writers may not overlap. Ordered overlapping writers require a verified handoff covering their complete shared scope between explicit execution lanes.
- Literal file scopes cannot authorize recursive directory scopes. Writer overlap is compared case-insensitively for portable Windows safety.
- A persistent task category belongs to at most one route. Multiple matches may share one route; conflicting routes are reported as ambiguous instead of being merged or selected by order. If no route matches, the current task is classified at runtime instead of defaulting blindly to direct execution.
- Runtime capability declarations require a probe and contract-preserving fallback when a special capability is needed.
- Runtime packets are bounded; challenges require evidence, relays cannot expand write scope, and required artifacts cannot be silently omitted.
- User-owned files and edits are never silently overwritten.
- Planned and recorded output paths reject case-only collisions and file/child target conflicts before transaction staging.
- Generated files are updated only when their recorded hash still matches.
- Outputs classified as unchanged are not rewritten.
- A failed multi-file apply is rolled back from verified backups before another plan may run. POSIX file permission modes are restored with content.
- Phase outputs are treated as frozen only when hashes were actually recorded.
- Authentication, permission, and quota failures are reported without pointless retries.
- Runtime and model settings are inherited unless workspace evidence requires an override.
- Code-changing work surfaces material ambiguity and simpler alternatives, uses the smallest scoped edit, avoids adjacent cleanup, defines verification before implementation, and reports unverified outcomes explicitly.

