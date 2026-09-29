# Bounded project maintenance

Read only when project maintenance is enabled and a stable concern is identified,
or a native maintenance hook supplies a review lease. Normal tasks do not require
a maintenance assessment, extra reviewer, whole-project scan, or additional model.

## Signals are not changes

Keep the harness unchanged by default. A scope expansion may use existing roles.
Ordinary bugs belong in project code. One failure, an unused agent, a new topic,
or an unverified low token count does not justify changing persistent structure.
Before recording a workflow/routing/verification gap, distinguish project defects
from a recurring missing instruction or responsibility. Use current source evidence.

Record a signal only at such an event, using an existing turn/run reference, never
raw conversation text. The file is a relevant project source, not a log or transcript:

```sh
harness-codex maintenance signal \
  --reason workflow-gap --evidence PROJECT.md --observation TURN_OR_RUN_REFERENCE
```

The CLI selects its dedicated interpreter; do not activate or alter the project environment. Reasons are
`scope-changed`, `workflow-gap`, `routing-mismatch`, `verification-gap`, `user-request`.
Distinct observations make a recurring concern eligible for review; they do not
prove the harness caused it. Explicit scope/user requests need only one signal.
Duplicate observations and already-reviewed concerns with identical evidence are
ignored. Only HMAC references and enums persist in user-local maintenance state.

## A review lease

`suggest` emits one notice per eligible batch, without running an automatic review.
`auto` may supply one review lease at the next user-turn boundary, provided no other
observed task or child agent is active. Review only those concerns before beginning
the user's new task. Do not spawn a separate reviewer or model. Default policy allows
two leases per rolling day. Adaptive intervals back off after unchanged reviews and
shorten with distinct repeated concerns, inside configured limits. Use the actual
lease deadline and status policy, never assume a fixed interval or time window.
An application window defaults to at most 180 seconds and can shrink from measured
review duration. Changing scheduling limits does not authorize broader edits.
Unknown native-session token usage stays unknown; this interface cannot enforce a
hard model-token budget. Stop early rather than expanding a maintenance review.

Status may show activity markers left by interrupted sessions. Never infer that
writers stopped from elapsed time or a failed connection. Use `recover-session`
only after explicit confirmation that the selected session and all its children
have stopped; never pass `--yes` merely to unblock your own review. Recovery keeps
other sessions, concerns and change history, and does not repair file transactions.

Read the current project-harness and the specific evidence needed for the concern.
Choose: keep unchanged, improve existing routing guidance, improve an existing skill,
or propose a separate configuration review. New roles are considered only when
recurring independent responsibility and verification needs justify their overhead.
Never reduce verification or claim a quality/cost benefit merely from token counts.

If unchanged, unsupported, or out of budget, finish the lease without file changes:

```sh
harness-codex maintenance finish \
  --lease LEASE_ID --decision unchanged
```

Decisions `proposed` and `deferred` also resolve the batch without rewriting the
harness. The same evidence must not cause another automatic review. Explain a
proposal or missing evidence concisely when relevant; an explicit `config` can
review broader changes without resetting the project. Never infer deletion/Git
authorization from this maintenance mode.

## Applying an existing-skill correction

Only an `auto` project permits this path. Read safe-update.md and follow the normal
plan builder/dry-run workflow. Keep the topology, capabilities, instruction pointer
and workspace contracts unchanged. Preserve user edits. At most two existing managed
SKILL.md files and 8 KiB of changed content can be applied per lease. Native agents,
new skills, permissions (including file modes), instructions outside those skills, and deletion are excluded.
Use a bounded temporary plan; do not persist model conversation or project content
in the maintenance store. Run task-relevant validation before applying; structural
validation alone does not prove a semantic improvement. If that cannot be verified
within the lease, choose `proposed` or `deferred`.

```sh
harness-codex maintenance finish \
  --lease LEASE_ID --decision apply --plan PATH_TO_VALIDATED_PLAN.json
```

The helper independently checks the current revision, observed concurrency,
deadline, scope, ownership, references and artifact contracts, and reuses journaled
apply/recovery. On conflict or interruption preserve the existing files/recovery
state; use `doctor` and the existing recovery protocol. Never refresh hashes manually.
Do not bypass this helper with direct file writes during automatic maintenance.

After a successful change, re-read the affected skill before the user's task.
Subsequent hooked turns receive a revision notice once per observed session.
Do not equate a notice with actual native discovery or correct execution. A broader
explicit `config` may require reload/resume or a fresh session for new native roles.

## Follow-up to a specific correction

Treat an applied change as instructions updated, effect under observation. Retain the
change ID and revision from the helper/revision notice in the current context.
Record only outcomes explicitly related to that correction, once per work item.
Do not infer a harness defect from an ordinary code bug, compare unrelated tasks,
guess a model/runtime identity, or call an extra evaluation model each turn.

```sh
harness-codex maintenance observe --change CHANGE_ID --revision USED_REVISION \
  --observation WORK_ITEM_ID --outcome failed --source verification \
  --model OBSERVED_MODEL --effort OBSERVED_EFFORT --category testing --runtime OBSERVED_RUNTIME
```

Use `unknown` or omit unavailable context. A verification source requires an actual
verification result; agent prose is `agent-reported`, never external ground truth.
If operations evidence is already enabled, attach `--maintenance-reason` and
`--maintenance-evidence` to its existing annotation for a specifically identified
gap, or `--maintenance-change` and `--maintenance-revision` for a related outcome;
include known `--model`, `--effort` and `--runtime`. Do not enable either feature
merely to create a record. The existing category and work-item ID are reused.

On `review-required`, `applying` or `rolling-back`, preserve the current project and stop automatic
corrections. Explain the status and request an explicit review. `resolve --decision
keep` acknowledges that review without claiming benefit. `resolve --decision
rollback --plan REVIEWED_PRIOR_PLAN.json` restores only the recorded prior bytes
after the normal ownership/revision checks. Never invent the previous content or
overwrite intervening user edits. Use config review if restoration is unavailable.
If explicit config superseded the recorded revision, inspect the current files and
use `keep` to close the old record without replacing the newer configuration.
Controlled effect evaluation remains optional and separate from these observations.

## Cost and limitations

Status separates counts, wall-clock review duration, optional agent-reported token
counts and unmeasured reviews. It never computes account billing or asserts savings.
Use the separate opt-in evaluator for controlled performance comparisons. Operations
hooks remain separate; maintenance does not enable per-turn outcome annotation.
Hooks require native trust; disabled/untrusted hooks do not provide concurrency or
automatic notices. Native sessions not using the trusted hook are outside observation.
The owner-authorized CLI init may prepare native trust for exact owned maintenance
hooks even while project modes are off. Trust alone never enables maintenance or
adaptive routing. The generator must not bypass trust or approve other hooks.
