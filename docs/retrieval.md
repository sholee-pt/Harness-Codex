# Optional local code retrieval

Graft is an optional navigation aid for large or repeatedly explored codebases.
It does not replace source inspection, Harness generation, tests or transaction
checks. Small known edits can keep ordinary search. No retrieval runs on normal
turns unless the agent actually chooses the retrieval skill.

Install Node.js 20 or newer and the reviewed Graft package separately on Linux:

```bash
DO_NOT_TRACK=1 npm install --prefix "$HOME/.local/share/harness-graft-runtime" @nanonets/graft@0.18.0
harness-codex graft enable --project /path/to/project \
  --package "$HOME/.local/share/harness-graft-runtime/node_modules/@nanonets/graft"
harness-codex graft status --project /path/to/project
harness-codex graft query "where is request routing selected" --project /path/to/project
```

Enable builds a structural index and installs the small optional
`.agents/skills/harness-retrieval/SKILL.md`. If the current native conversation
does not discover the skill, open a fresh conversation or invoke the query
explicitly. Existing project agents, the manifest and root instructions are
unchanged. No new agent is required.

The adapter calls reviewed structural library APIs directly, bypassing Graft
CLI startup, automatic version checks, init, global hooks and telemetry. It
never enables the LLM/deep pass. Project inputs are not sent to a model or a
hosted graph service. Graft remains a separately installed MIT dependency;
its license is retained in that package, and it is not bundled into Harness.
Other versions require adapter review instead of silently guessing API behavior.

Queries refresh only when the structural fingerprint changes, reuse parse
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
records and caches survive tool uninstall, like project harnesses. A cloned
project does not authorize execution through another user's saved settings.

Character-based estimates from Graft are not reported as measured token savings.
Measure actual task correctness, elapsed time, billed tokens and rework on paired
tasks, including initial indexing and maintenance cost, before claiming benefit.
Windows native Graft validation is not part of this Linux release.

Upstream: [trailhq/Graft](https://github.com/trailhq/Graft).
