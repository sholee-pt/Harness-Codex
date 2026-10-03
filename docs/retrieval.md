# Local code retrieval

Graft is a navigation aid for large or repeatedly explored codebases.
It does not replace source inspection, Harness generation, tests or transaction
checks. Small known edits can keep ordinary search. No retrieval runs on normal
turns unless the agent actually chooses the retrieval skill.

On Linux, ordinary `init` prepares and enables retrieval after the project harness
validates. An existing configured project can run the same command without
regenerating its agents or skills:

```bash
harness-codex init --project /path/to/project
harness-codex graft status --project /path/to/project
harness-codex graft query "where is request routing selected" --project /path/to/project
```

The first preparation downloads an official Node 22 Linux archive, verifies its
published SHA-256 and installs the reviewed `@nanonets/graft@0.18.0` package into
user-local storage. Other projects reuse this runtime without another download.
No sudo, global npm installation, system PATH or Conda environment change is
required. First setup needs access to nodejs.org and registry.npmjs.org and can
take several minutes; progress includes elapsed time and npm details go to a
local log on failure. A failed dependency setup does not fail an otherwise
successful project configuration. Retry without a package path:

```bash
harness-codex graft enable --project /path/to/project
harness-codex init --project /path/to/project --retrieval off
```

Explicit disable is remembered, including before the first setup; ordinary init
does not undo it. `graft enable` explicitly re-enables it. `init --dry-run` and
`init --install-only` never set up retrieval. `config` and `reset` preserve the
choice unless `--retrieval auto|off` is supplied. Automatic setup targets Linux
x86_64 and aarch64; the release smoke runs on x86_64. Other platforms retain ordinary source search.
For an already installed dependency, `graft enable --package PATH --node PATH`
keeps the manual/offline route available.

Initial activation builds a structural index and installs the small optional
`.agents/skills/harness-retrieval/SKILL.md`. If the current native conversation
does not discover the skill, open a fresh conversation or invoke the query
explicitly. Existing project agents, the manifest and root instructions are
unchanged. No new agent is required.

The adapter calls reviewed structural library APIs directly, bypassing Graft
CLI startup, automatic version checks, init, global hooks and telemetry. It
never enables the LLM/deep pass. Graft itself sends no project inputs to a model
or hosted graph service. Init also enables [Jev shadow advice](jev.md), which can
send bounded query results to TypeSafe when a saved key or TYPESAFE_API_KEY is
available. Init offers guided key setup; only explicit new-key entry makes a
fixed non-project authentication call. Explicit Jev disable remains disabled
on later init.
Graft remains a separately installed MIT dependency;
its license is retained in that package, and it is not bundled into Harness.
Other versions require adapter review instead of silently guessing API behavior.

Repeated init reuses an enabled setup without probing the source tree or
rebuilding its graph. Queries refresh only when the structural fingerprint changes, reuse parse
results and return at most six hits and 12,000 characters by default. Adjust
`--limit` (1-20), `--max-chars` (512-64000) and `--timeout` (up to 240 seconds)
when needed. No hook rebuilds the index after every turn. Index misses, missing
languages, busy builds, incomplete builds and unavailable dependencies require
ordinary source search, never a blocked coding session. A structural graph is
not proof of complete runtime dependencies, data semantics or model correctness.

```bash
harness-codex graft rebuild --project /path/to/project
harness-codex graft disable --project /path/to/project
```

Rebuild explicitly reparses changed inputs with the existing extraction cache.
Disable removes only an unchanged owned retrieval skill; user modifications are
preserved. It retains the disposable index for later re-enabling. Project opt-in
and dependency provenance live in the current user's
`~/.local/share/harness-codex-retrieval/`, keyed by the absolute project path.
`HARNESS_GRAFT_HOME` can select a different dedicated storage directory. These
records, isolated runtime and caches survive tool uninstall, like project harnesses. A cloned
project does not authorize execution through another user's saved settings.

Character-based estimates from Graft are not reported as measured token savings.
Measure actual task correctness, elapsed time, billed tokens and rework on paired
tasks, including initial indexing and maintenance cost, before claiming benefit.
Windows native Graft validation is not part of this Linux release.

## Explicit external code

Keep the main graph scoped to the project. Attach only needed external code with a named binding:

```bash
harness-codex graft add /shared/library/model.py --name model-library --project /work/project
harness-codex graft add /shared/library/src --name shared-src --project /work/project
harness-codex graft query "where is prediction implemented" --project /work/project
harness-codex graft status --project /work/project
harness-codex graft remove model-library --project /work/project
```

An external binding is a local read selection, not permission to modify that code.
Only source-code extensions are included: at most 16 bindings, 200 files, 1 MiB per
file and 16 MiB in total. Select a narrower directory when a limit is reached.
Project ancestors, hidden metadata/environment directories and nested links are
excluded or refused. An explicitly selected directory alias is resolved first.
No automatic home/ancestor scan or external discovery takes place.

Queries retain the primary project graph and use a separate, project-specific
structural index for selected external files. Unchanged snapshots are reused;
changed files refresh on demand. Results identify original source locations.
This does not infer dependency edges between the two graphs. Missing external
sources and empty external results retain the full primary candidates and text.
Jev uses the same project candidates whether or not external sources are selected.
`--limit` bounds project hits; external retrieval can add up to half that many
hits (rounded down, at least one) when queried. The default is therefore at most
six project and three external hits. External text uses only the remaining
`--max-chars` budget and never cuts project text. When space is exhausted,
`--json` reports `externalDisplayed: false` and `truncated: true`; increase
`--max-chars` to display it. If even the external heading cannot fit, external
collection and indexing are skipped (`externalSkipped: output-budget-exhausted`),
so no external hit count is claimed. `--limit 1` still permits one external hit
when output space remains. External failures are reported in `externalWarning`
and in text when the remaining budget permits.
External results never enter Jev network advice. Removing a binding immediately
excludes it from queries; disposable snapshots may remain in user-local cache.
Opt-ins, executable provenance and external bindings are local selections, so
reselect them after moving to another server or changing the project mount path.
Settings, Jev state, bundled Node/package roots and index bindings are partitioned by a stable local host
identity even when two servers share the same home and absolute project path.
The older unscoped layout is preserved; its explicit Graft/Jev opt-outs remain
effective until explicitly enabled, but its executable paths and external
bindings are not imported into the new host scope.

New configuration records ownership of the unchanged static retrieval skill in
the portable context receipt. Init on a new host can reuse that file while
preparing a locally selected runtime; it does not import the old host's executable
path, credentials or external bindings. For a legacy skill without that receipt,
`harness-codex graft enable --adopt-skill --project PATH` explicitly adopts only
the byte-identical bundled skill. Modified/user-authored skills remain preserved.

Before Jev advice starts, the query rechecks Graft settings under the settings
lock. A completed disable prevents a new advice request from that older query.
An already running bounded advice call can temporarily keep the settings lock;
a disable command that reports lock contention has not completed the preference
change and can be repeated after the call finishes.

For broader adoption, compare selective retrieval on cross-file edits, interface
discovery and change-impact questions first. Upstream also provides callers,
file API and repository-map tools; this adapter currently exposes bounded query
retrieval only. Automatic prompt injection, every-turn rebuilds and the optional
LLM deep pass are not enabled. Those additions need separate evaluation of
correctness and total cost, including setup, extra context and failed attempts.
Upstream's published benchmarks use different agent/model setups and do not
establish the benefit of this Harness-Codex integration.

Upstream: [trailhq/Graft](https://github.com/trailhq/Graft).
