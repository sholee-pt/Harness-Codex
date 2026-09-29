# Project maintenance

Maintenance is opt-in. Ordinary conversations do not run a separate evaluation
model, rescan the project or regenerate the harness. Scope growth is a review
signal, not a rule to create agents. Source-code defects stay project-code work.

After configuring or recognizing an existing harness, interactive `init` explains
and offers maintenance (`off`, `suggest`, `auto`) and adaptive Auto evidence
(`off`, `on`). Enter keeps each current choice; a new project starts with both
off. Esc cancels these preference choices without applying either. The generated
harness remains in place. Explicit `--maintenance` / `--adaptive` flags skip their
respective menu. JSON, redirected output, dry-run and install-only never prompt;
`config` and `reset` preserve these choices unless explicit flags are supplied.
Inspect or change them later with the commands below and `harness-codex routing
--adaptive status|on|off`. Adaptive Auto is a separate option; it neither selects
Auto in `/model` nor automatically judges task quality.

```sh
harness-codex init --goal-file PROJECT.md --maintenance suggest
harness-codex maintenance --mode auto
harness-codex maintenance
harness-codex maintenance --json
harness-codex maintenance --mode off
# Explicitly reset local concerns/session observations and disable maintenance:
harness-codex maintenance clear --yes
```

`suggest` collects narrowly identified concerns and displays one review notice per
eligible batch. `auto` authorizes bounded existing-skill corrections after review.
Both install a user-level native hook without replacing unrelated hooks. Use
`/hooks` in Codex to review/trust the new or changed handler. Trust is never granted
by Harness. If hooks are not enabled and trusted, automatic notices and concurrency
observation are unavailable. The trusted SessionStart hook supplies concise signal
instructions once per session/policy; UserPromptSubmit supplies them if startup was
missed. A mode change or compaction refreshes the guidance. Ordinary later turns
receive no repeated policy text and do not trigger a review without eligible signals.

The handler uses the native [Codex hooks contract](https://developers.openai.com/codex/hooks/).
It checks the installed tool's integrity and bounded local state, not every project
file. This incurs local process/filesystem work, even when no model review is due.

## When anything changes

Explicit scope changes and independently recurring workflow/routing/verification
gaps become candidates. Only selected source evidence is read. Duplicate signals
are merged; already-reviewed evidence is suppressed, including no-change results.
Signals are assessments, not proof of root cause. Current source evidence must
justify a persistent correction before anything is applied.

At a subsequent turn boundary, auto mode may reserve one review batch. The native
agent reviews only that batch in the existing conversation; it does not spawn an
extra reviewer. The default adaptive policy permits at most two reviews in a rolling
24-hour window. Its interval starts at one hour, backs off after unchanged reviews,
and shortens as distinct relevant observations accumulate, within five minutes and
24 hours. Recent completed review duration adjusts the application window up to
180 seconds by default. Review lease, manifest revision and observed concurrent
tasks/children are checked before apply. New agents, new skills, topology changes,
permission changes, instruction-pointer changes and deletion use explicit `config`.
Automatic changes are limited to two existing managed skills and 8 KiB of changed
content. Ownership, reference integrity and journaled recovery stay enabled.

`--schedule` is an advanced control for the review interval, not a background job
or a model-evaluation switch. Most users can omit it: new policies use `adaptive`,
and repeated init preserves any existing setting. `adaptive` adjusts the interval
from concerns and review outcomes; `fixed` uses one hour within the configured
limits. Neither runs a review without eligible concerns. The init menus do not
change this policy. These settings never expand edit scope:

```sh
harness-codex maintenance --schedule adaptive --max-reviews-per-day 2 \
  --min-interval-seconds 300 --max-interval-seconds 86400 --max-review-seconds 180
harness-codex maintenance --reported-token-budget 4000
harness-codex maintenance --reported-token-budget 0
```

The optional reported-token budget pauses further reviews after an unmeasured
review or when the reported daily total reaches the limit. It cannot prevent an
ongoing native model call from exceeding that limit. Status shows this distinction
and the currently calculated interval/window. Resolved candidate slots are retired
as needed with a bounded seven-day suppression record; unresolved concerns are
never discarded to make room. Ordinary turns do not need another model call.

The same conversation can re-read an updated skill immediately; subsequent hooked
turns receive a revision notice. A notice is not proof the model followed it.
Explicitly added native components require discovery verification and may require
resume or a fresh conversation. A missing hook means unobserved native sessions
cannot be included in concurrency checks.

## Records and costs

Records are user-local, outside the project: enums, local HMAC references, revisions
and bounded counters. Raw prompts, responses, transcripts and source content are
not retained. The operations/evaluation collectors remain separate and default-off.
Maintenance tracks review counts/duration and distinguishes optional reported token
counts from unavailable measurements. It does not compute account billing or claim
quality/cost improvements. Its application deadline is enforced by the helper;
a hard reasoning-token cap inside the native interactive model is not available.
Use the separately requested paired evaluator to measure any benefit.

Tool uninstall removes its exact registered hook handler but retains project-local
policies and user-local observations so reinstall can recognize them. `maintenance
clear --yes` resets this selected project's observations and disables maintenance;
it does not touch project files, other projects or native Codex history. Use it to
recover from stale session observations after an interrupted native process.

Status reports unknown quality honestly. If maintenance conflicts, times out or
finds no justified change, keep the harness and continue project work. Recovery
of an interrupted file transaction uses the existing `doctor`/recovery protocol.
See the [generator maintenance protocol](../.agents/skills/harness/references/maintenance.md).

## Change outcomes and recovery

Each automatic correction records an opaque change ID, before/after manifest revisions, reason/evidence references and the prior/new hashes of affected skills. The bounded user-local history stores no skill text, model IDs, paths or transcripts. Local state schemas 1 and 2 are read as schema 3 in memory; a status read does not rewrite them and existing off/suggest/auto choices remain unchanged. Init/config display maintenance and adaptive Auto preferences; controlled task-effect comparison remains a separate opt-in procedure.

Applied changes start as `observing`: instructions updated, effect not established. The next hooked request carries a one-time revision notice and change ID. Record an outcome only when it is explicitly related to that correction, with the revision actually used by the task. Known model, effort, task category and runtime identity are hashed into a context group; unknown context remains descriptive and cannot trigger a comparison. Multiple records of one work item count once. Two independent, externally reported adverse outcomes in one known context group pause further automatic changes (`review-required`); they do not prove causality or stop ordinary work. Positive reports never automatically become a measured quality/cost benefit.

```sh
harness-codex maintenance --json
harness-codex maintenance observe --change CHANGE_ID --revision REVISION \
  --observation WORK_ITEM_ID --outcome failed --source verification \
  --model OBSERVED_MODEL --effort OBSERVED_EFFORT --category testing --runtime OBSERVED_CODEX_VERSION
harness-codex maintenance resolve --change CHANGE_ID --decision keep
harness-codex maintenance resolve --change CHANGE_ID --decision rollback --plan REVIEWED_PRIOR_PLAN.json
```

`resolve` is an explicit review action. Rollback requires an independently reviewed plan restoring exactly the prior recorded skill bytes; no project backup is hidden in evaluation state. It refuses changed revisions, user edits, topology changes, observed live writers and pending transactions. Interrupted apply/rollback leaves an intent record that pauses new changes; recover any file transaction, wait for the review lease to expire, then explicitly resolve it. A completed rollback can close its intent without repeating writes. If explicit config has already replaced that revision, inspect it and use `keep` to close the prior record as `superseded`; rollback cannot overwrite the newer configuration. Without a prior plan, use explicit config review rather than guessing old content. The history retains at most 16 changes with 32 outcome records each; only reviewed, rolled-back or superseded entries can be retired to make space. Local state is bounded at 512 KiB, with oversized writes refused before replacing the previous record.

Existing operations annotations can optionally carry `--maintenance-reason` plus `--maintenance-evidence`, or `--maintenance-change` plus `--maintenance-revision` and observed model/effort/runtime. They reuse the existing work-item ID. An ordinary failed task does not create a maintenance signal. Maintenance failures preserve the independent operations record, and neither path enables the other automatically. Controlled before/after evaluation remains separate; this history does not learn model-routing policy or automatically tune Jev/Graft.
