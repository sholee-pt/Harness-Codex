# Local Operations Evidence

Operations evidence is an opt-in, user-local record of how an installed Harness is used across interactive Codex turns. It does not change generated files, persistent topology, routing, evaluation records, or the manifest.

## Work-item boundary

One Codex session may contain unrelated tasks, refinements, corrections, and later verification. The session is therefore not the unit of analysis. Every observed `UserPromptSubmit` turn creates a distinct pseudonymous work item. A later enum-only annotation may classify it as:

- `new-task`;
- `acceptance`;
- `refinement`;
- `correction`;
- `follow-up`;
- `reopen`;
- `cancel`; or
- `unclassified` when the relationship is not established.

Relationships may point only to an earlier work item in the same session. They make explicit acceptance, correction, or reopen feedback visible without rewriting the earlier record. They do not prove that the earlier answer was wrong or that the new answer is correct.

## Opt-in hook

Run `harness_ops.py hooks-template` to print a user-level Codex `hooks.json` candidate. The command creates a file only when `--output` is supplied and refuses to replace an existing file. Review or trust new and modified hooks with Codex `/hooks`; Harness never bypasses hook trust.

The handler accepts `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, and `SessionEnd`. It searches upward from the hook working directory and records an event only when it finds a current Manifest Schema 6 local-only Harness workspace. All other directories are ignored. The handler is fail-open so an observability error cannot block the user's task.

The hook returns an enum-only annotation reminder for each user turn. The annotation is evidence supplied by the running agent, not a trusted semantic oracle. Users may add a later user-reported annotation when acceptance or correction is actually known.

## Evidence semantics

An annotation separates:

- task category;
- direct, delegated, coordinated, or unknown execution;
- appropriate, questionable, inappropriate, not-applicable, or unknown agent-selection fit;
- unknown, passed, failed, or not-applicable verification;
- verified, provisionally accepted, user accepted, needs revision, failed, abandoned, or unknown outcome; and
- agent-reported, user-reported, verification, or hook-observed source.

`verified` requires passed verification. `user-accepted` requires user-reported evidence. A completed turn or a `Stop` event alone never becomes a successful outcome. Missing evidence stays unknown.

Subagent start and stop events support task-level agent-use and incomplete-lifecycle signals. An agent-selection classification is an explicit assessment, not proof that the selected agent was appropriate, that its configuration was loaded, or that its output caused the final result. `questionable` and `inappropriate` selections produce review signals.

## Audit and adaptation boundary

`audit` summarizes each work item, relationships, task categories, execution classes, agent-selection assessments, verification, outcomes, pseudonymous agent use, later corrections or reopens, dangling subagent lifecycles, and invalid records. It returns one of:

- `healthy` when every recorded item has non-adverse classified evidence;
- `insufficient-evidence` when tasks are unclassified or outcomes remain unknown;
- `review-recommended` when adverse outcomes or incomplete subagent lifecycles are observed; or
- `state-invalid` when record integrity fails.

The audit always reports `regenerationRecommended: false`. Evidence is a trigger for human or agent review, not permission to rewrite topology. Repeated route mismatch, corrections concentrated around one responsibility, or unused agents may justify a new project audit only after current workspace evidence confirms a stable boundary or workflow change.

## Privacy, retention, and integrity

Operations Event Schema 1 stores one immutable hash-sealed file per event. It retains local HMAC references, timestamps, finite enums, and integrity metadata. It does not retain raw prompts, responses, transcripts, agent names, agent IDs, absolute workspace paths, commands, or source content. The repository registry stores only a keyed locator and a random repository ID.

Each workspace is limited to 4,096 operations events. Once the limit is reached, the hook remains fail-open, emits a generic local warning, and records nothing further until the user audits and purges the collection. The audit exposes the limit condition explicitly.

State uses `HARNESS_STATE_HOME` when set, otherwise the platform user-local Harness state directory. It must remain outside the observed workspace. `purge --root WORKSPACE` explicitly removes operations event files for that workspace; it does not remove project files or evaluation records.

The local store is not encrypted at rest and is not a compliance log. HMAC pseudonyms prevent raw identifiers from appearing in records but do not make a compromised local account safe.
