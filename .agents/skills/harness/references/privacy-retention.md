# Privacy and Retention

Harness evaluation and operations state does not retain raw prompts, structured report files, raw component names, transcripts, reasoning, messages, commands, command output, source code, file contents, absolute repository paths, remote URLs, user email, environment values, secrets, free-form notes, or raw JSONL.

Repository, prompt, model, agent, skill, route, check, and result references use a local secret where a stable fingerprint is needed. Agent and skill pseudonyms retain 128 bits of HMAC output. The secret is never exported.

## State root

Resolution order is:

1. `HARNESS_STATE_HOME`;
2. the platform user-local state directory; or
3. an explicit error.

The resolved state directory may not contain, or be contained by, the target repository or either paired worktree. This prevents evaluation data from changing the project or contaminating a comparison.

Records use per-run files, same-directory temporary writes, `fsync`, atomic replacement, and advisory repository locks. Completed runs, observations, annotations, comparisons, and proposals are immutable. Observation and annotation corrections create a linked successor instead of replacing a file. Corrupt files are skipped with an explicit warning and moved only by `repair --quarantine`; graph conflicts are reported rather than guessed away.

Opt-in Operations Event Schema 1 uses the same user-local root and pseudonymous repository registry but a separate `operations/events` collection. Each user turn is a distinct work item. Event files retain only timestamps, HMAC references, finite classifications, and integrity metadata. A later annotation supersedes an earlier annotation without replacing it. `harness_ops.py purge` removes only operations events for the selected workspace.

`purge` preserves active pending records. When none remain, it removes completed records and auxiliary records before deleting the pseudonymous registry mapping as the final step.

## Service boundary

`--ephemeral` prevents local Codex session rollout persistence. It does not mean that the configured Codex service or model provider receives no task data. Harness has no remote telemetry of its own; service-side processing and retention follow the user's Codex account and provider policy.

The local store is not encrypted at rest, does not provide signed audit logs, and is not a regulatory compliance system.
