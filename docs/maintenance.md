# Project maintenance

Maintenance is opt-in. Ordinary conversations do not run a separate evaluation
model, rescan the project or regenerate the harness. Scope growth is a review
signal, not a rule to create agents. Source-code defects stay project-code work.

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
observation are unavailable. A new/resumed Harness conversation supplies the mode's
signal instructions; an already-open conversation must re-read them or be resumed.

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
extra reviewer. At most two reviews per day, at least an hour apart, may apply a
change within 180 seconds. Review lease, manifest revision and observed concurrent
tasks/children are checked before apply. New agents, new skills, topology changes,
permission changes, instruction-pointer changes and deletion use explicit `config`.
Automatic changes are limited to two existing managed skills and 8 KiB of changed
content. Ownership, reference integrity and journaled recovery stay enabled.

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
