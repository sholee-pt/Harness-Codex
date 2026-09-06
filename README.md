<p align="center">
  <img src="https://img.shields.io/badge/Harness_for_Codex-v9.3-brightgreen.svg" alt="Harness for Codex v9.3">
  <img src="https://img.shields.io/badge/Runtime-Codex-111827.svg" alt="Codex Runtime">
  <img src="https://img.shields.io/badge/Type-Harness_Generator-orange.svg" alt="Harness Generator">
  <img src="https://img.shields.io/badge/License-Proprietary-blue.svg" alt="Proprietary License">
</p>

# Harness for Codex

> Generate the smallest evidence-backed Codex agent system that matches a project's persistent decision boundaries.

Harness provides a standalone Linux command and a Codex skill, with project-local generator installation by default. Run it inside a local project workspace and it analyzes the available evidence, selects only justified agent and skill boundaries, and writes a native project harness for later work. A workspace may be a plain directory or a local Git work tree; GitHub is not required.

## Install with the Linux bootstrap

`install_harness.sh` handles source download, version selection, the dedicated Conda environment and installation of the `harness` command. GitHub CLI (`gh`) and manually downloading/checking release archives are not required. Linux needs Git, tar and Anaconda or Miniconda; the initial download below also uses curl. Codex CLI must be installed and authenticated separately.

**Private repository authentication is required for the first download too.** `git config user.name` and `user.email` identify commit authors; they do not grant GitHub access. Use an existing `GITHUB_TOKEN`/`GH_TOKEN` with read access to this repository, or the SSH/source route below. The bootstrap can reuse a Git credential helper or SSH credentials once it has been downloaded, but it cannot authenticate a curl request that runs before the script exists. See [GitHub authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github).

If you have not already provided an access token in the environment, enter it locally without putting its value in shell history:

```bash
set +x
read -r -s -p 'GitHub token with Harness Contents read access: ' GITHUB_TOKEN
printf '\n'
export GITHUB_TOKEN
```

Then download the versioned bootstrap and install. The token is passed through curl's input, not its URL or command arguments:

```bash
set +x
printf 'Authorization: Bearer %s\n' "${GITHUB_TOKEN:-${GH_TOKEN:-}}" |
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --header @- --header 'Accept: application/vnd.github.raw+json' \
    'https://api.github.com/repos/sholee-pt/Harness/contents/install_harness.sh?ref=codex-v9.3' \
    --output install_harness.sh &&
  bash install_harness.sh --runtime codex
export PATH="$HOME/.local/bin:$PATH"

harness --version
harness --help
```

The versioned bootstrap link remains available when old version branches are removed. Running it without `--branch` selects the highest numeric Codex branch, fetches its exact source commit into temporary tool storage, validates the downloaded tree, and invokes the existing safe installer. It does not select an unrelated Claude release or use commit author information as authentication. Credentials remain in the process environment/credential provider; Harness never writes token values to its configuration, source, project, or logs. An environment token remains usable for later updates when it is supplied again; Harness does not save it.

If you use SSH authentication and have no HTTPS token, curl cannot use your SSH key. Use the existing Git transport for the initial source download instead:

```bash
git clone --depth 1 --branch codex/v9.3 git@github.com:sholee-pt/Harness.git Harness &&
  bash Harness/install.sh --runtime codex --repository git@github.com:sholee-pt/Harness.git
export PATH="$HOME/.local/bin:$PATH"
```

An already downloaded `install_harness.sh` also supports `--repository git@github.com:sholee-pt/Harness.git`. Without an explicit transport, it tries the fixed repository over HTTPS and then SSH using existing credentials. If the server has only an author name/email and no actual repository credential, installation reports the missing authentication instead of claiming success. No sudo or automatic shell-profile edits are used. The installer never replaces the active project environment, such as `scRAE`; the installed command uses its own `harness` environment.

## Configure and work

The project folder must already exist. It may contain no Git repository, one repository, or multiple repositories.

```bash
harness init --project /absolute/path/to/project --goal "Describe the work this project will support"
harness start --project /absolute/path/to/project
harness start --project /absolute/path/to/project "Fix the preprocessing error and verify it"
harness doctor --project /absolute/path/to/project
```

`init` installs the generator inside the project and opens interactive Codex with the appropriate skill selected. Continue the conversation normally; native trust, login and approval prompts remain in effect. Exit Codex to let Harness verify the generated manifest. For later sessions, `start` selects the project harness internally, including projects with existing user-owned `AGENTS.md`. You do not need to type `$harness` or `$project-harness`. Fresh sessions discover newly generated instructions and agents; valid files do not prove model quality or actual agent loading.

Ordinary source edits can make recorded evidence stale. When all safety/ownership checks pass, `start` asks Codex to re-read current source; it does not rewrite or declare the manifest valid. Deleted or renamed evidence blocks `start`, but `init`/`configure` can perform fresh analysis and reviewed replacement. Malformed references, symlinks, nonregular files, changed managed files and contract errors still block unsafe work.

| Command | Behavior |
| --- | --- |
| `harness --version`, `harness --help` | Local information, no network or model call |
| `harness init --project PATH` | Safe generator installation and interactive project configuration |
| `harness init --project PATH --dry-run` | No writes, update check or Codex call |
| `harness init --project PATH --install-only` | Generator installation only |
| `harness configure --project PATH` | Review the project harness with the installed current generator |
| `harness start --project PATH ["TASK"]` | Interactive Codex with the project harness selected |
| `harness doctor --project PATH` | Read-only installed-state and activation diagnosis |
| `harness update --check` | Read-only upstream branch check |
| `harness update` | Update tool code; existing project artifacts remain unchanged |

## Codex and future Claude support

The product direction is one `harness` command with separate runtime adapters and release channels. Codex is the default, and can be made explicit:

```bash
harness --runtime codex init --project /absolute/path/to/project
harness start --runtime codex --project /absolute/path/to/project
harness update --runtime codex --check
```

Claude CLI integration is not implemented in this release. `--runtime claude` is recognized and exits with that explanation before environment preparation, downloads or file changes; it never runs Codex as a substitute. Existing `claude/*` branches do not imply compatibility with the new CLI.

| Component | Codex | Future Claude adapter |
| --- | --- | --- |
| User command | `harness --runtime codex ...` | Same command, explicit Claude runtime |
| Source branch | `codex/vN[.M]` | `claude/vN[.M]` |
| Release tag | `codex-vN.M` | `claude-vN.M` |
| Archive | `harness-codex-N.M-linux.tar.gz` | Separate Claude-named archive |
| Native generated files | Codex agents, skills and project manifest | Claude-native files and distinct ownership contracts |

Runtime version numbers are independent: a higher Claude version must never replace a Codex installation. The existing Codex data path and project schemas stay compatible in v9.3. Before implementing the second runtime, active versions, receipts, locks and update histories must be separated per runtime with a reviewed migration. Merely broadening the current branch filter would create ownership collisions and is not supported.

## Updates and ownership

Tool releases live under `${XDG_DATA_HOME:-$HOME/.local/share}/harness-cli`, separately from project-generated files. The launcher uses the real `harness` Conda interpreter. Managed files, launchers and active pointers are checked before replacement. Modified files cause a conflict; interrupted activation preserves the previous active release.

Before interactive `init`, `configure` or `start`, the default policy checks at most once per day and installs forward updates within the same major version. It never replaces a running session's code. Major upgrades require explicit `harness update`. Offline or authentication failures retain the current installation and report the problem. Git uses an existing credential helper/SSH transport, or `GITHUB_TOKEN` then `GH_TOKEN` for this repository's HTTPS requests. Git author identity is not used for access.

```bash
bash install_harness.sh --auto-update check  # Notify only
bash install_harness.sh --auto-update off    # No automatic checks
harness start --project /path/to/project --no-update-check
harness update --check --branch codex/v9.3
harness update --branch codex/v9.3 --repository git@github.com:sholee-pt/Harness.git
```

Use `--bin-dir /absolute/bin/path --data-dir /absolute/tool/path` for custom installation locations, repeating those paths when reinstalling or changing installer settings. Keep tool storage outside the project. Without a branch pin, only numeric Codex branches are considered. Source commits and forward ancestry are checked, but branch selection itself does not assert a successful CI run or live model performance.

Tool updates do not regenerate project agents automatically. Use `harness init --project PATH` to install the new generator and review a project update. Valid v9.0/v9.1/v9.2 artifacts remain compatible. Operations recording and comparative evaluation are still optional and off by default.

## Manual release archive

[GitHub Releases](https://github.com/sholee-pt/Harness/releases/tag/codex-v9.3) also provides `harness-codex-9.3-linux.tar.gz`, `install_harness.sh`, `SHA256SUMS` and source-bound `build.json`. Download the first three files before running `sha256sum --check SHA256SUMS`; a checksum file cannot be checked before it exists. The archive is a Python-based tool, not a bundled Codex/model binary.

```bash
sha256sum --check SHA256SUMS &&
  tar -xzf harness-codex-9.3-linux.tar.gz &&
  bash harness-codex-9.3/install.sh
```

The repository home page's About settings control whether Releases appears in the sidebar. This is separate from publishing a release and from repository visibility. Private releases require repository access. See [GitHub release management](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

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
git clone --branch codex/v9.3 --single-branch https://github.com/sholee-pt/Harness.git Harness
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

Harness for Codex v9.3 retains a strict shared skill-frontmatter parser and binds every generated agent's instruction contract to its structured topology. It does not ask the model to reproduce fixed change-discipline or runtime-teamplay contracts. Authoring Contract 3 drafts use path-specific placeholders, and `harness_plan_builder.py` deterministically materializes a normal Schema 3 plan before the existing apply validator runs. Every project router and generated agent receives its required canonical block exactly once; an old draft revision, unsafe output path, or missing, duplicate, or misplaced placeholder fails before any workspace write.

The installed skill includes `references/minimal-draft-plan.json`, so plan authoring does not depend on repository-only test fixtures.

## v9.3 compatibility and validation

v9.3 adds authenticated bootstrap installation and explicit runtime selection to the standalone command introduced in v9.2 while retaining the selected-folder contract introduced in v9.0 and the installer fixes/Git advice introduced in v9.1. It uses Manifest Schema 7 and Artifact Contract 2 with `project-local` workspace scope and `gitProtection: {"mode": "not-managed", "patterns": []}`. Authoring Contract 3 and Plan Schema 3 remain unchanged; materialize existing drafts again to produce the current artifact contract.

Valid v9.0, v9.1, v9.2 and v9.3 installations share this artifact contract. A v9.0 installation or valid Artifact Contract 2 plan remains accepted without the new advice; updating the generator does not silently rewrite existing project artifacts. A reviewed rematerialization adds the advice, and normal apply checks hashes before updating files. Installer maintenance and project-artifact validity are separate.

Clean recognized v7.0–v7.6 Schema 6 installations without an artifact marker and v8.0/v8.1 Schema 6 installations with Artifact Contract 1 report `upgrade-required` (exit 2). Corruption, unsupported combinations, or a missing required v8 agent block report `invalid` (exit 1). Upgrade through a reviewed draft, materialization, dry-run, hash-checked apply, and installed validation. Existing Git exclusion blocks are preserved rather than removed automatically. Version-field edits alone are not an upgrade. Schema 4/5 regeneration remains a separate guarded path. See [generated artifact contracts](.agents/skills/harness/references/generated-contracts.md).

The runtime remains standard-library-only. The optional test oracle is pinned separately to PyYAML 6.0.1. Structural tests and static instruction byte counts do not establish live token savings, runtime loading, or a scRAE performance result.

## Activation Diagnostics

After generation, run the read-only diagnostic when installation or activation is unclear:

```shell
conda run -n harness python TARGET_PROJECT/.agents/skills/harness/scripts/harness_doctor.py --root TARGET_WORKSPACE
```

The report checks the dedicated environment and installed-state validation, then distinguishes `managed-pointer` from `explicit-skill` activation. `configured` means the files and activation contract validate; `runtimeLoaded: not-tested` means live loading has not been observed. A missing Codex CLI does not invalidate a desktop installation. The diagnostic never launches Codex, installs hooks, or repairs files. Use the mode-aware [live smoke test](.agents/skills/harness/references/codex-smoke-test.md) when actual discovery or delegation must be observed.

For a small direct task, the generated router keeps scope, expected output, and verification in the current task. It does not require a separate runtime-plan file, coordination packet, relay receipt, or disposable capability probe. Explicit planning requests and required quality checks still apply. If the task later needs delegation, validate the ephemeral plan before spawning. The canonical runtime contract remains unchanged; this is a reduction of unnecessary task artifacts, not a measured token-saving claim.

## Selected Project Folders

Harness accepts plain folders, Git roots, Git-contained subfolders, linked worktrees, and folders containing multiple repositories. Git boundaries are context for analyzing responsibilities; they do not replace the user's selected project root or automatically prohibit a scoped writer inside a nested repository. Write scopes and evidence must remain inside the selected folder, and symlink or junction escapes remain rejected.

Generation does not query GitHub or remotes and does not modify Git metadata, exclusions, the index, commits, branches, or deployment settings. Generated files may appear in Git status and may be tracked if the user chooses. Harness neither guarantees that they remain ignored nor changes existing user or legacy exclusion rules. File ownership and recorded hashes govern safe updates independently of Git tracking.

For later project work, requested source edits and tests remain allowed within scope. Commit and push each need authorization covering that operation; commit approval alone does not authorize push. Force push, history rewriting, branch deletion, and discarding work need approval covering that destructive action. Existing approval remains usable only for its authorized repository, work, and destination. New routers and agents receive this advice without a new required artifact block. Harness does not intercept shell commands or API calls: strict enforcement depends on the actual executor's permission controls. See [Git authorization policy](.agents/skills/harness/references/git-authorization.md).

Inventory Schema 5 and Root Context Schema 3 report known Git boundaries and bounded scan coverage. Truncated or unreadable coverage is an uncertainty to report, not proof of absent boundaries or a demand to move the selected root. Existing user-owned instructions remain unchanged and select `explicit-skill` activation; invoke `$project-harness` directly. Harness never creates an override merely to bypass existing project guidance.

## Optional Local Operations Evidence

Harness for Codex v9.3 can observe long-running interactive use without treating one CLI session as one task. Each `UserPromptSubmit` turn becomes a separate pseudonymous work item. Subagent lifecycle events, enum-only execution and agent-selection assessments, verification state, outcome, and an optional relationship to an earlier turn are attached to that work item. Explicit acceptance, correction, refinement, follow-up, reopened work, cancellation, or an unrelated new task can therefore be distinguished inside the same session.

This mode is disabled until the user explicitly installs the user-level hook. Generate a candidate configuration first:

```shell
conda run -n harness python TARGET_PROJECT/.agents/skills/harness/scripts/harness_ops.py hooks-template
```

If `~/.codex/hooks.json` does not exist, it may be created explicitly with `--output ~/.codex/hooks.json`. Existing hook files are never overwritten; merge the printed entries manually and review or trust them with `/hooks`. The handler ignores directories without a current project-local Harness manifest, so installing the user hook does not turn every filesystem directory into a Harness workspace.

The hook stores no raw prompt, response, transcript, agent name, or absolute path. Local HMAC references and finite enums are written only to the user-local Harness state directory. Completion is not treated as success, agent-reported success is not user acceptance, and missing evidence remains `unknown`. Operations evidence never changes topology or regenerates agents automatically.

```shell
conda run -n harness python TARGET_PROJECT/.agents/skills/harness/scripts/harness_ops.py audit --root TARGET_WORKSPACE
conda run -n harness python TARGET_PROJECT/.agents/skills/harness/scripts/harness_ops.py purge --root TARGET_WORKSPACE
```

An audit reports task-level routing, agent use, verification, adverse outcomes, later correction or reopen relationships, and evidence gaps. It is a review signal rather than proof of semantic quality. See [operations-evidence.md](.agents/skills/harness/references/operations-evidence.md) for trust, privacy, retention, and interpretation rules.

## Optional Evaluation

Harness for Codex v9.3 can record local metadata for an explicitly requested run, compare isolated with/without-Harness arms, attribute results only to a plan-bound declared or preassigned configuration delta, ingest structured observations, and probe change-discipline decisions against synthetic cases. The delta comes from immutable arm configuration snapshots; it does not prove that every declared route, agent, skill, or policy was used at runtime. Evaluation is disabled by default and does not change generation, ownership, apply, recovery, operations evidence, or runtime-teamplay validation behavior.

```shell
conda run -n harness python .agents/skills/harness/scripts/harness_eval.py run \
  --root TARGET_REPOSITORY \
  --task-file TASK.txt \
  --sandbox read-only

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py list

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py add-observation \
  --run RUN_ID \
  --report OBSERVATION.json

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py view \
  --run RUN_ID

conda run -n harness python .agents/skills/harness/scripts/harness_eval.py change-discipline-suite \
  --root TARGET_REPOSITORY \
  --cases tests/fixtures/evaluation/change-discipline-cases.json
```

Run records distinguish measured empty sets, unavailable values, and non-applicable concepts. Schema 2 separately records declared configuration, expected execution, runtime discovery, and observed execution. Raw prompts, reports, component names, transcripts, commands, paths, source content, and JSONL events are not written to Harness evaluation state. `--ephemeral` prevents local Codex rollout persistence; service-side processing still follows the configured Codex account and provider policy.

The `view` output includes a presentation-only `usageSummary` that preserves selected measurements, reported-only values, missing counters, conflicts, and partial coverage. Terminal-event counters do not establish parent-only, all-child, or account-wide usage. Harness does not sum overlapping counters or infer billing cost. Comparison plans can select `input-tokens`, `cached-input-tokens`, `output-tokens`, and `reasoning-output-tokens` individually; these are counter comparisons, not total-cost attribution. See [capture-provenance.md](.agents/skills/harness/references/capture-provenance.md). Existing records and comparison view fingerprints are not rewritten by this display supplement.

The change-discipline suite checks a model's declared decision and behavior tags for four synthetic cases: material ambiguity, a one-line direct change, a file-scoped bug fix, and verification-first handling of a reproducible bug. It is a classification probe, not proof that a later code-editing run followed the declared behavior. Use `--validate-only` to validate the fixture without invoking Codex.

See [evaluation-contract.md](.agents/skills/harness/references/evaluation-contract.md) for the boundary, [run-record-schema.md](.agents/skills/harness/references/run-record-schema.md) for schemas, and [evaluation-isolation.md](.agents/skills/harness/references/evaluation-isolation.md) before paired runs.

Paired runs require a clean Git-root source with a valid Harness for Codex v9.3 project-local installation, exactly one registered worktree, untracked Harness-managed outputs, and Comparison Plan Schema 2. These are optional evaluation preconditions; they do not restrict generation. The user chooses the source Git exclusion/cleanliness policy, since generation no longer installs one. The evaluator verifies and snapshots manifest-managed files, every manifest-referenced evidence file, and bounded project context that can alter Codex behavior: root instruction candidates, `.codex/config.toml`, unmanaged `.codex/agents/*.toml`, and unmanaged `.agents/skills/**`. It then creates two independent local clones at that commit, removes every remote, and gives each clone its own Git metadata and exclusion file. Tracked, ignored, and untracked evidence and project context are materialized identically in both arms. All destinations in both arms are checked before the first write, including lexical symlink, Windows reparse-point, directory-collision, and namespace conflicts. Evidence under `.git/**` or `.harness/**` is rejected before content is read or hashed.

The baseline removes generated-only instruction files completely, then re-runs the same root instruction discovery used during generation so an existing fallback can become active. If a managed instruction file also contains preserved user content but its exact pre-install bytes are unavailable, that content remains in both arms and the comparison records `baseline-instruction-provenance-unavailable`, making it descriptive rather than eligible for concrete attribution. Immediately before clean synthetic pre-task commits are created, the evaluator rechecks evidence and project-context bytes and modes, absence of baseline Harness state, treatment validity, remote removal, source commits, allowed changed paths, and instruction selection. Ignored context is literal force-added to both task bases, and the indexed blob and executable bit are verified so later fingerprints measure changes to those paths. A present `.codex/config.toml` is preserved and hashed, but materialization is not proof that Codex effectively loaded it: until a deterministic load receipt exists, the pair records `project-config-load-unverified`, remains partial, and cannot support concrete configuration attribution. Likewise, unmanaged custom-agent files are preserved symmetrically, but their registry discovery, selected configuration layer, external skill references, and MCP dependencies are not inferred from file presence. A pair containing them records `project-agent-load-unverified` and remains descriptive until deterministic discovery and selected-agent dependency receipts exist. User and project rules are intentionally disabled by `--ignore-rules`; project hooks are not enabled by this evaluator. Paired runs accept `--repetitions` and an `--order` policy of `randomized`, `counterbalanced`, `baseline-first`, or `harness-first`. Task fingerprinting and patch-scope measurement occur immediately after Codex exits. Verification profiles must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status; a changed or non-quiescent repository is retained descriptively with partial comparability and a `verification-repository-state-mutated` gap. Verification runs in a dedicated process group and its cleanup must be confirmed. Known Harness skills in user, compatibility, Codex-home, or readable POSIX admin locations downgrade isolation; a dirty dedicated `CODEX_HOME` is rejected. Fixed arm order is retained as an explicit confounder. Windows runs require a matching user-local cleanup receipt before isolation can be labelled complete.

Default `paired-run --dry-run` validates source prerequisites without cloning and separately reports project-context discovery, project-config presence, custom-agent count, `projectConfigMaterialized: false`, effective configuration and agent-load status, dependency-verification status, and an unobserved remote-retention result. Add `--validate-materialization` to create disposable clones, reconstruct both arms, verify their task bases, and report exact context materialization and the actually observed no-remote result without invoking Codex or writing evaluation state.

Structured reports use raw logical component IDs only as user-owned input. Ingest validates those IDs against the immutable configuration snapshot attached to that run, stores only local HMAC pseudonyms, and never copies the report. Observations are create-only supplements, replacements, or terminal withdrawals. Annotation Schema 2 similarly maintains one active user-outcome chain. The `view` command computes current selected values, field-specific provenance, protocol deviations, and conflicts without persisting a second source of truth.

Patch-scope evaluation is optional. A user-owned profile declares allowed path scopes and budgets; rename and copy operations count both affected paths. If untracked files exist while a line budget is active, completeness is conservatively partial because their line count is not inferred. The run stores only its digest, counts, and pseudonymous path references. It verifies path scope, not semantic minimality.

Concrete positive or negative configuration attribution requires `propose --comparison-plan PLAN.json`. The plan hash and attribution target must match every included comparison. Proposal support counts only complete comparisons made from independent Run pairs; partial comparisons remain individually inspectable but are excluded from pair counts, direction statistics, and candidates. Reusing either Run in the same attribution group excludes every connected comparison instead of selecting a favorable subset. A changed Observation or Annotation makes its older Comparison stale, while a new Comparison over the same Run pair is allowed when the Derived View fingerprints differ. If more than one concrete-eligible evaluation stratum remains, `propose` requires an explicit `--evaluation-stratum SHA256` instead of choosing a favorable group; a well-formed fingerprint that is absent from the matching comparisons is an error rather than a no-change proposal. Without a verified plan, or with a descriptive-only target, Harness emits only an experiment suggestion or no-change record and leaves the candidate empty. When a plan declares patch scope, both arms must have a complete matching measurement and stay within the declared limits; incomplete or violated scope remains descriptive evidence but cannot support a concrete proposal.

## Runtime Teamplay

Harness for Codex v9.3 keeps persistent workspace topology separate from current-task execution. It creates no permanent team merely because multiple agents exist. A temporary runtime plan selects `direct`, `delegated`, or `coordinated` execution from interaction value: independent work delegates, one review pass uses delegated producer-reviewer, and only repeated feedback, conflicting expert judgment, cross-boundary agreement, or dynamic reassignment justifies coordination.

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

See [teamplay-contract.md](.agents/skills/harness/references/teamplay-contract.md), [runtime-plan.md](.agents/skills/harness/references/runtime-plan.md), [native-subagent-relay.md](.agents/skills/harness/references/native-subagent-relay.md), [runtime-observation.md](.agents/skills/harness/references/runtime-observation.md), [relay-receipt.md](.agents/skills/harness/references/relay-receipt.md), and [team-recipes.md](.agents/skills/harness/references/team-recipes.md). v9.3 keeps Codex as the execution engine while using canonical receiver handles for bounded control, optional versioned public/local observation profiles for evidence, required-task accounting, and hash-bound offline review lineage. Capability policies use a small canonical registry so validated names cannot silently select a different fallback path. Missing observation evidence lowers confidence without cancelling a valid handle execution; verified binding or terminal-outcome contradictions fail closed.

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

## Validation

The generator includes standard-library-only Python tools. Run them through the dedicated Conda environment:

```shell
conda run -n harness python .agents/skills/harness/scripts/inventory.py .
conda run -n harness python .agents/skills/harness/scripts/harness_state.py evidence --root . --path PATH_TO_EVIDENCE
conda run -n harness python .agents/skills/harness/scripts/harness_state.py status --root .
conda run -n harness python .agents/skills/harness/scripts/harness_plan_builder.py --root . --input DRAFT_PLAN.json --output PLAN.json
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --plan PATH_TO_PLAN.json --dry-run
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --inspect-transaction
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --recover
conda run -n harness python .agents/skills/harness/scripts/harness_apply.py --root . --clean-orphaned-transaction
conda run -n harness python .agents/skills/harness/scripts/validate_harness.py .
conda run -n harness python .agents/skills/harness/scripts/validate_runtime_plan.py --root . --plan PATH_TO_RUNTIME_PLAN.json
conda run -n harness python .agents/skills/harness/scripts/validate_coordination_packet.py --root . --plan PATH_TO_RUNTIME_PLAN.json --packet PATH_TO_PACKET.json
conda run -n harness python .agents/skills/harness/scripts/harness_runtime_receipt.py --root . --plan PATH_TO_RUNTIME_PLAN.json --jsonl PATH_TO_CODEX_EVENTS.jsonl --public-profile codex-public-jsonl-core-v1 --control-plane-report PATH_TO_CONTROL_PLANE_REPORT.json --codex-cli-version 0.152.1 --execution-mode persistent --repository-id repo-0123456789abcdef --harness-commit 0123456789abcdef0123456789abcdef01234567 --salt-file PATH_TO_TEMPORARY_SALT
conda run -n harness python .agents/skills/harness/scripts/harness_relay_receipt.py --root . --plan PATH_TO_RUNTIME_PLAN.json --receipt PATH_TO_RELAY_RECEIPT.json
conda run -n harness python .agents/skills/harness/scripts/evaluate_topology.py --plan PATH_TO_PLAN.json --golden PATH_TO_GOLDEN.json
conda run -n harness python .agents/skills/harness/scripts/harness_eval.py --help
conda run -n harness python -m unittest discover -s tests -v
```

Inventory Schema 5 reports the selected workspace kind, bounded scan coverage, Conda manifests, conservative file roles, known nested Git boundaries, and research-output directories separately. Known output directories are excluded from content classification by default and may be inspected deliberately with `--include-artifacts`. Scan uncertainty never changes the selected root. Existing instruction precedence and the instruction path Harness could safely manage are reported separately.

`evaluate_topology.py` validates only the persistent topology contract and reports `evidenceValidated: false`. It does not replace the evidence, ownership, and no-write checks performed by `harness_apply.py --dry-run`.

Use `--recover` only when status or a failed apply reports a pending journal. Use `--inspect-transaction` before maintenance. `--clean-orphaned-transaction` is restricted to the reserved staging directory when no journal exists; it never replaces recovery for a valid journal. Recovery first verifies that interrupted outputs were not edited externally and refuses destructive cleanup when their hashes are unknown.

If Windows Conda raises `UnicodeEncodeError` while forwarding a child-process error, inspect transaction status before retrying and rerun the diagnostic with `conda run --no-capture-output -n harness python ...`. This keeps the required environment while exposing the original Harness result.

Harness for Codex v9.3 uses Manifest Schema 7, Artifact Contract 2, Inventory Schema 5, and Root Context Schema 3. Authoring Contract 3, generation Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, coordination-packet Schema 1, relay-receipt Schema 1, Runtime Receipt Schema 2, and Evaluation Schema 2 remain unchanged. Operations Event Schema 1 remains separate user-local evidence. Evaluation records through v9.2 remain readable descriptively; only current v9.3 runs in complete, independent, plan-verified pairs support concrete attribution. Persistent topology is not changed by runtime, relay, receipt, operations, or evaluation validation.

## Versioning

- Harness for Codex releases use `codex/vN` or `codex/vN.M` branches. The number identifies the Harness release, not the Codex product version.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Displayed Harness and generator versions use two components (`N.M`). Existing major branches such as `codex/v5` represent their `.0` release and remain unchanged.
- Breaking generator changes start a new branch version.

See [VERSIONS.md](VERSIONS.md) for compatibility, migration, and release differences.

Claude-native editions are maintained independently on the repository's `claude/*` branches.

## License

This repository is proprietary and intended for the copyright holder's private use. See [LICENSE](LICENSE).
