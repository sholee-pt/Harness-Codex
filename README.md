<h1 align="center">Harness for Codex</h1>

<p align="center">
  Project-local orchestration with Codex-native agents and skills.
</p>

<p align="center">
  <a href="https://github.com/sholee-pt/Harness/releases/tag/codex-v9.8"><img src="https://img.shields.io/badge/Harness_for_Codex-v9.8-2563EB.svg?style=flat-square" alt="Harness for Codex v9.8"></a>
  <a href="#codex-and-future-claude-editions"><img src="https://custom-icon-badges.demolab.com/badge/Agent-Codex-111827.svg?style=flat-square&amp;logo=openai&amp;logoColor=white" alt="Agent: Codex"></a>
  <a href="#what-it-generates"><img src="https://img.shields.io/badge/Type-Harness_Generator-7C3AED.svg?style=flat-square" alt="Type: Harness Generator"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Proprietary-64748B.svg?style=flat-square" alt="License: Proprietary"></a>
</p>

<p align="center">
  <a href="environment.yml"><img src="https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <a href="#one-command-linux-installation"><img src="https://img.shields.io/badge/Platform-Linux-334155.svg?style=flat-square&amp;logo=linux&amp;logoColor=white" alt="Platform: Linux"></a>
  <a href="#one-command-windows-installation"><img src="https://custom-icon-badges.demolab.com/badge/Platform-Windows-0078D4.svg?style=flat-square&amp;logo=windows11&amp;logoColor=white" alt="Platform: Windows"></a>
</p>

<p align="center">
  <a href="#one-command-linux-installation">Linux install</a> &middot;
  <a href="#one-command-windows-installation">Windows install</a> &middot;
  <a href="#configure-and-use-a-project">Quick start</a> &middot;
  <a href="https://github.com/sholee-pt/Harness/releases/tag/codex-v9.8">Release</a> &middot;
  <a href="VERSIONS.md">Changelog</a>
</p>

Generate and maintain a project-local harness using Codex-native agents and skills. The Linux and Windows command is **`harness-codex`**. Project folders may be plain directories, Git worktrees or multi-repository workspaces.

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
bash Harness/installers/install.sh
```

The retired `install_harness.sh` Git bootstrap has been removed from this branch. For private access, use an authenticated Git clone and the source installer above. The installed CLI retains its authenticated HTTPS/SSH update support. Git author name/email are not authentication. Codex CLI installation and login remain prerequisites for actual Codex sessions; version/help, installation and diagnosis do not require a model call.

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
& ([scriptblock]::Create((Get-Content ./Harness/installers/install.ps1 -Raw))) -SourceRoot (Resolve-Path ./Harness).Path
```

## Configure and use a project

```bash
harness-codex init --project /path/to/project --goal-file /path/to/project-brief.md
harness-codex start --project /path/to/project
harness-codex config --project /path/to/project --goal-file /path/to/project-brief.md
harness-codex start --project /path/to/project "Fix the preprocessing error and verify it"
```

`init` installs the generator inside the project and starts interactive Codex with the generator selected. If a harness already exists, plain `init` reports its state; supplying a brief requests a reviewed update. `--install-only` installs or updates just the generator. Installed `init` also restores missing user PATH registration on Linux or Windows, except during `--dry-run`. Continue normal conversation in Codex; `$harness` or `$project-harness` need not be typed manually. Trust, login, model, sandbox and approval settings remain native to Codex. On return, Harness checks the generated manifest; valid files do not establish live agent loading or task quality.

`config` is the public configuration command. The previous `configure` spelling remains a compatibility alias for existing scripts and dispatches to the same handler. `--goal` describes the project for `init`, `config` and `reset`; `--goal-file` reads an existing UTF-8 `.md`/`.markdown` file up to 64 KiB. They are mutually exclusive. Relative brief paths resolve from the invoking directory. A brief may be outside the project when explicitly selected; it is reference material, not extra authorization. Its path is not stored as a persistent project setting. `start` accepts an optional task argument instead.

| Command | Behavior |
| --- | --- |
| `harness-codex --version`, `--help` | Local information without network or a model call |
| `harness-codex init --project PATH` | Install the project generator and open configuration |
| `harness-codex init --project PATH --dry-run` | Preview without writes, PATH changes, updates or Codex |
| `harness-codex init --project PATH --install-only` | Install only the generator |
| `harness-codex config --project PATH` | Review project configuration |
| `harness-codex start --project PATH ["TASK"]` | Open the project session |
| `harness-codex status --project PATH` | Report installation state and next action |
| `harness-codex doctor --project PATH` | Validate installed artifacts and activation contracts |
| `harness-codex update --check` | Inspect upstream without installing |
| `harness-codex update` | Update tool code between sessions |

Ordinary source-content drift can recommend `start` to re-read source. Missing evidence requires a reviewed `config`. Changed managed files, malformed references, links and contract errors retain the existing blocking behavior. No diagnostic silently updates manifest hashes. `status` exit code 0 means the state query completed, not that every validation passed; inspect its state and summary, or use `doctor` for validation.

## Updates and existing installations

Fresh installations use `${XDG_DATA_HOME:-$HOME/.local/share}/harness-codex` and `~/.local/bin/harness-codex`. The separate Miniforge fallback, when needed, is in the sibling `harness-codex-conda` directory. The launcher preserves the caller's project environment. Existing Conda environments are reused; Git is added to the dedicated `harness` environment only if unavailable both there and on PATH. Project dependencies are not installed by Harness.

Existing v9.2–v9.6 generic `harness` installations keep their recorded command and data directory when updated, so old launchers and automation continue to work. Run the new installer with default locations to adopt the separate `harness-codex` command. An explicitly reused legacy `--data-dir` retains its recorded launcher name; it does not silently rename user commands. Existing `HARNESS_TOOL_HOME` identifies an installed invocation, while installer defaults remain in the Codex namespace unless `--data-dir` is explicit.

```bash
harness-codex update
harness-codex init --project /path/to/project --install-only
harness-codex config --project /path/to/project
```

Tool updates preserve project agents and skills. The last two commands separately adopt new generator guidance through a reviewed configuration update. Valid v9.0–v9.8 project artifacts remain compatible. Existing v9.2–v9.4 legacy launchers can be repaired with `harness update --repair-launcher`; current launchers are unchanged. Reinstalling the same tool source preserves file bytes and modification times. Managed source or launcher edits are refused rather than overwritten.

Default automatic updates check at most once a day before interactive work and accept verified forward versions within the same major release. Use `--auto-update check` or `--auto-update off` when installing to change the policy; `--no-update-check` suppresses an invocation's automatic check. Explicit `update` can select a major version. Branch selection alone does not prove successful CI or improved model performance. Help, version, status, doctor and dry-run stay offline.

## Remove or reset a project harness

```bash
harness-codex remove --project /path/to/project                     # Preview
harness-codex remove --project /path/to/project --yes               # Apply
harness-codex remove --project /path/to/project --include-generator --yes
harness-codex reset --project /path/to/project --goal-file brief.md  # Preview
harness-codex reset --project /path/to/project --goal-file brief.md --yes
harness-codex remove --project /path/to/project --recover --yes      # Recover interrupted removal
```

Removal preserves modified/unowned files and Git metadata. `reset` preflights the brief, generator and native Codex, then removes owned artifacts and starts new configuration. It cannot undo arbitrary changes made during that session. Use `config` for a reviewed update without removal. Interrupted operations retain ownership-checked recovery state; preserve it and use the matching recovery command. These commands operate on the selected project and do not uninstall the CLI or remove Bash PATH entries.

## Codex and future Claude editions

Provider identity is part of the executable, bootstrap, tool storage and release asset names:

| Component | Codex | Future Claude edition |
| --- | --- | --- |
| Command | `harness-codex` | `harness-claude` |
| Public installer | `install_harness_codex.sh` / `.ps1` | Separate Claude installers |
| Tool data directory | `harness-codex` | Separate Claude-owned directory |
| Source branch | `codex/vN[.M]` | `claude/vN[.M]` |
| Tag / archive | `codex-vN.M` / `harness-codex-N.M-linux.tar.gz` | Separate Claude tag and archive |

Only Codex is implemented. No Claude installer or executable is published as a placeholder. Compatibility options `--agent codex` and hidden `--runtime codex` remain accepted; conflicting assertions or Claude selection fail without launching another provider. Project-native formats and ownership contracts must be implemented separately before a Claude edition ships.

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
git clone --branch codex/v9.8 --single-branch https://github.com/sholee-pt/Harness.git Harness
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

Harness for Codex v9.8 retains a strict shared skill-frontmatter parser and binds every generated agent's instruction contract to its structured topology. It does not ask the model to reproduce fixed change-discipline or runtime-teamplay contracts. Authoring Contract 3 drafts use path-specific placeholders, and `harness_plan_builder.py` deterministically materializes a normal Schema 3 plan before the existing apply validator runs. Every project router and generated agent receives its required canonical block exactly once; an old draft revision, unsafe output path, or missing, duplicate, or misplaced placeholder fails before any workspace write.

The installed skill includes `references/minimal-draft-plan.json`, so plan authoring does not depend on repository-only test fixtures.

## v9.8 compatibility and validation

v9.8 adds conditional model-workflow guidance, separates source evidence from managed-artifact diagnostics and clarifies reviewer and native execution checks. It retains v9.5's source completeness checks, caller-environment preservation, guarded launcher repair and bootstrap Git deadlines. Manifest Schema 7 and Artifact Contract 2 retain `project-local` workspace scope and `gitProtection: {"mode": "not-managed", "patterns": []}`. Authoring Contract 3 and Plan Schema 3 remain unchanged; older generated projects do not require regeneration solely for this maintenance release.

Valid v9.0, v9.1, v9.2, v9.3, v9.4, v9.5, v9.6 and v9.8 installations share this artifact contract. A v9.0 installation or valid Artifact Contract 2 plan remains accepted without the new advice; updating the generator does not silently rewrite existing project artifacts. A reviewed rematerialization adds the advice, and normal apply checks hashes before updating files. Installer maintenance and project-artifact validity are separate.

`status`, `doctor` and installed validation include a `summary` separating managed-artifact checks, source-evidence checks, runtime loading and task quality. A normal source-content change can leave the first check passed and the second failed; `status` recommends `start` to re-read current source while preserving the recorded manifest. Missing references still require a reviewed `configure`, and managed-file changes or other contract failures remain blocked. Runtime loading stays `not-tested` and task quality stays `not-measured` in these offline diagnostics, including after a structurally valid installation.

For model/training/benchmark work, [model-workflows.md](.agents/skills/harness/references/model-workflows.md) provides conditional analysis questions and an adaptable comparison note. The generator selects only relevant procedures from actual project evidence; it does not add a fixed ML team. A source hash or a structurally valid checklist does not establish scientific correctness. [generation-quality-evaluation.md](.agents/skills/harness/references/generation-quality-evaluation.md) separates repeated fresh authoring from deterministic materialization and downstream with/without-Harness task comparisons. Use [codex-smoke-test.md](.agents/skills/harness/references/codex-smoke-test.md) for bounded native checks and distinguish automatic selection from explicitly passing instructions to a child.

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

Harness for Codex v9.8 can observe long-running interactive use without treating one CLI session as one task. Each `UserPromptSubmit` turn becomes a separate pseudonymous work item. Subagent lifecycle events, enum-only execution and agent-selection assessments, verification state, outcome, and an optional relationship to an earlier turn are attached to that work item. Explicit acceptance, correction, refinement, follow-up, reopened work, cancellation, or an unrelated new task can therefore be distinguished inside the same session.

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

Harness for Codex v9.8 can record local metadata for an explicitly requested run, compare isolated with/without-Harness arms, attribute results only to a plan-bound declared or preassigned configuration delta, ingest structured observations, and probe change-discipline decisions against synthetic cases. The delta comes from immutable arm configuration snapshots; it does not prove that every declared route, agent, skill, or policy was used at runtime. Evaluation is disabled by default and does not change generation, ownership, apply, recovery, operations evidence, or runtime-teamplay validation behavior.

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

Paired runs require a clean Git-root source with a valid Harness for Codex v9.8 project-local installation, exactly one registered worktree, untracked Harness-managed outputs, and Comparison Plan Schema 2. These are optional evaluation preconditions; they do not restrict generation. The user chooses the source Git exclusion/cleanliness policy, since generation no longer installs one. The evaluator verifies and snapshots manifest-managed files, every manifest-referenced evidence file, and bounded project context that can alter Codex behavior: root instruction candidates, `.codex/config.toml`, unmanaged `.codex/agents/*.toml`, and unmanaged `.agents/skills/**`. It then creates two independent local clones at that commit, removes every remote, and gives each clone its own Git metadata and exclusion file. Tracked, ignored, and untracked evidence and project context are materialized identically in both arms. All destinations in both arms are checked before the first write, including lexical symlink, Windows reparse-point, directory-collision, and namespace conflicts. Evidence under `.git/**` or `.harness/**` is rejected before content is read or hashed.

The baseline removes generated-only instruction files completely, then re-runs the same root instruction discovery used during generation so an existing fallback can become active. If a managed instruction file also contains preserved user content but its exact pre-install bytes are unavailable, that content remains in both arms and the comparison records `baseline-instruction-provenance-unavailable`, making it descriptive rather than eligible for concrete attribution. Immediately before clean synthetic pre-task commits are created, the evaluator rechecks evidence and project-context bytes and modes, absence of baseline Harness state, treatment validity, remote removal, source commits, allowed changed paths, and instruction selection. Ignored context is literal force-added to both task bases, and the indexed blob and executable bit are verified so later fingerprints measure changes to those paths. A present `.codex/config.toml` is preserved and hashed, but materialization is not proof that Codex effectively loaded it: until a deterministic load receipt exists, the pair records `project-config-load-unverified`, remains partial, and cannot support concrete configuration attribution. Likewise, unmanaged custom-agent files are preserved symmetrically, but their registry discovery, selected configuration layer, external skill references, and MCP dependencies are not inferred from file presence. A pair containing them records `project-agent-load-unverified` and remains descriptive until deterministic discovery and selected-agent dependency receipts exist. User and project rules are intentionally disabled by `--ignore-rules`; project hooks are not enabled by this evaluator. Paired runs accept `--repetitions` and an `--order` policy of `randomized`, `counterbalanced`, `baseline-first`, or `harness-first`. Task fingerprinting and patch-scope measurement occur immediately after Codex exits. Verification profiles must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status; a changed or non-quiescent repository is retained descriptively with partial comparability and a `verification-repository-state-mutated` gap. Verification runs in a dedicated process group and its cleanup must be confirmed. Known Harness skills in user, compatibility, Codex-home, or readable POSIX admin locations downgrade isolation; a dirty dedicated `CODEX_HOME` is rejected. Fixed arm order is retained as an explicit confounder. Windows runs require a matching user-local cleanup receipt before isolation can be labelled complete.

Default `paired-run --dry-run` validates source prerequisites without cloning and separately reports project-context discovery, project-config presence, custom-agent count, `projectConfigMaterialized: false`, effective configuration and agent-load status, dependency-verification status, and an unobserved remote-retention result. Add `--validate-materialization` to create disposable clones, reconstruct both arms, verify their task bases, and report exact context materialization and the actually observed no-remote result without invoking Codex or writing evaluation state.

Structured reports use raw logical component IDs only as user-owned input. Ingest validates those IDs against the immutable configuration snapshot attached to that run, stores only local HMAC pseudonyms, and never copies the report. Observations are create-only supplements, replacements, or terminal withdrawals. Annotation Schema 2 similarly maintains one active user-outcome chain. The `view` command computes current selected values, field-specific provenance, protocol deviations, and conflicts without persisting a second source of truth.

Patch-scope evaluation is optional. A user-owned profile declares allowed path scopes and budgets; rename and copy operations count both affected paths. If untracked files exist while a line budget is active, completeness is conservatively partial because their line count is not inferred. The run stores only its digest, counts, and pseudonymous path references. It verifies path scope, not semantic minimality.

Concrete positive or negative configuration attribution requires `propose --comparison-plan PLAN.json`. The plan hash and attribution target must match every included comparison. Proposal support counts only complete comparisons made from independent Run pairs; partial comparisons remain individually inspectable but are excluded from pair counts, direction statistics, and candidates. Reusing either Run in the same attribution group excludes every connected comparison instead of selecting a favorable subset. A changed Observation or Annotation makes its older Comparison stale, while a new Comparison over the same Run pair is allowed when the Derived View fingerprints differ. If more than one concrete-eligible evaluation stratum remains, `propose` requires an explicit `--evaluation-stratum SHA256` instead of choosing a favorable group; a well-formed fingerprint that is absent from the matching comparisons is an error rather than a no-change proposal. Without a verified plan, or with a descriptive-only target, Harness emits only an experiment suggestion or no-change record and leaves the candidate empty. When a plan declares patch scope, both arms must have a complete matching measurement and stay within the declared limits; incomplete or violated scope remains descriptive evidence but cannot support a concrete proposal.

## Runtime Teamplay

Harness for Codex v9.8 keeps persistent workspace topology separate from current-task execution. It creates no permanent team merely because multiple agents exist. A temporary runtime plan selects `direct`, `delegated`, or `coordinated` execution from interaction value: independent work delegates, one review pass uses delegated producer-reviewer, and only repeated feedback, conflicting expert judgment, cross-boundary agreement, or dynamic reassignment justifies coordination.

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

See [teamplay-contract.md](.agents/skills/harness/references/teamplay-contract.md), [runtime-plan.md](.agents/skills/harness/references/runtime-plan.md), [native-subagent-relay.md](.agents/skills/harness/references/native-subagent-relay.md), [runtime-observation.md](.agents/skills/harness/references/runtime-observation.md), [relay-receipt.md](.agents/skills/harness/references/relay-receipt.md), and [team-recipes.md](.agents/skills/harness/references/team-recipes.md). v9.8 keeps Codex as the execution engine while using canonical receiver handles for bounded control, optional versioned public/local observation profiles for evidence, required-task accounting, and hash-bound offline review lineage. Capability policies use a small canonical registry so validated names cannot silently select a different fallback path. Missing observation evidence lowers confidence without cancelling a valid handle execution; verified binding or terminal-outcome contradictions fail closed.

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

Harness for Codex v9.8 uses Manifest Schema 7, Artifact Contract 2, Inventory Schema 5, and Root Context Schema 3. Authoring Contract 3, generation Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, coordination-packet Schema 1, relay-receipt Schema 1, Runtime Receipt Schema 2, and Evaluation Schema 2 remain unchanged. Operations Event Schema 1 remains separate user-local evidence. Evaluation records through v9.6 remain readable descriptively; only current v9.8 runs in complete, independent, plan-verified pairs support concrete attribution. Persistent topology is not changed by runtime, relay, receipt, operations, or evaluation validation.

## Versioning

- Harness for Codex releases use `codex/vN` or `codex/vN.M` branches. The number identifies the Harness release, not the Codex product version.
- Harness for Claude Code releases use runtime-specific `claude/vN` or `claude/vN.M` branches.
- Displayed Harness and generator versions use two components (`N.M`). Existing major branches such as `codex/v5` represent their `.0` release and remain unchanged.
- Breaking generator changes start a new branch version.

See [VERSIONS.md](VERSIONS.md) for compatibility, migration, and release differences.

Claude-native editions are maintained independently on the repository's `claude/*` branches.

## License

This repository is proprietary and intended for the copyright holder's private use. See [LICENSE](LICENSE).
