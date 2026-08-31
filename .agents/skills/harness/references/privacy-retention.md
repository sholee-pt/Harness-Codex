# Privacy and Retention

Harness evaluation state does not retain raw prompts, transcripts, reasoning, messages, commands, command output, source code, file contents, absolute repository paths, remote URLs, user email, environment values, secrets, free-form notes, or raw JSONL.

Repository, prompt, model, agent, skill, route, check, and result references use a local secret where a stable fingerprint is needed. Agent and skill pseudonyms retain 128 bits of HMAC output. The secret is never exported.

## State root

Resolution order is:

1. `HARNESS_STATE_HOME`;
2. the platform user-local state directory; or
3. an explicit error.

The resolved state directory may not contain, or be contained by, the target repository or either paired worktree. This prevents evaluation data from changing the project or contaminating a comparison.

Records use per-run files, same-directory temporary writes, `fsync`, atomic replacement, and advisory repository locks. Completed records are immutable. Corrupt files are skipped with an explicit warning and moved only by `repair --quarantine`.

`purge` preserves active pending records. When none remain, it removes completed records and auxiliary records before deleting the pseudonymous registry mapping as the final step.

## Service boundary

`--ephemeral` prevents local Codex session rollout persistence. It does not mean that the configured Codex service or model provider receives no task data. Harness has no remote telemetry of its own; service-side processing and retention follow the user's Codex account and provider policy.

The local store is not encrypted at rest, does not provide signed audit logs, and is not a regulatory compliance system.
