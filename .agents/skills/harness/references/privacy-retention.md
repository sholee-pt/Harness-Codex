# Privacy and Retention

Harness evaluation and operations state does not retain raw prompts, structured report files, raw component names, transcripts, reasoning, messages, commands, command output, source code, file contents, absolute repository paths, remote URLs, user email, environment values, secrets, free-form notes, or raw JSONL.

Repository, prompt, model, agent, skill, route, check, and result references use a local secret where a stable fingerprint is needed. Agent and skill pseudonyms retain 128 bits of HMAC output. The secret is never exported.

## State root

Resolution order is:

1. `HARNESS_STATE_HOME`;
2. the platform user-local state directory; or
3. an explicit error.

The resolved state directory may not contain, or be contained by, the target repository or either paired worktree. This prevents evaluation data from changing the project or contaminating a comparison.

Records use per-run files, same-directory temporary writes, `fsync`, atomic replacement, and advisory repository locks. Completed runs, observations, annotations, comparisons, and proposals are immutable. Observation and annotation corrections create a linked successor instead of replacing a file. Invalid history blocks derived views and lifecycle mutations rather than silently reactivating a predecessor. Listing identifies corrupt runs, export counts excluded records, and repair reports invalid files; only explicit `repair --quarantine` moves them. Quarantining a successor removes it from the remaining history, so review the reported damage before using the repaired view. Graph conflicts are reported rather than guessed away.

Opt-in Operations Event Schema 1 uses the same user-local root with a separate selected-workspace registry namespace and `operations/events` collection. Each user turn is a distinct work item. Event files retain only timestamps, HMAC references, finite classifications, and integrity metadata. A later annotation supersedes an earlier annotation without replacing it. `harness_ops.py purge` removes only operations events for the selected workspace. Legacy Git-root records remain separate; do not silently attribute mixed historical records to one project.

Evaluation `purge` preserves active pending records and deletes evaluation records and their auxiliaries. It retains opaque registry mappings so concurrent writers and retained operations records cannot become unreachable. These mappings store no raw paths. Optional adaptive routing and maintenance use separate bounded state: their explicit clear commands disable those features and reset only their own records. Adaptive routing keeps at most 256 pseudonymous work items; feedback corrections replace that item's outcome rather than creating extra independent evidence. Their descriptive observations are not the immutable paired-evaluation log and do not establish causal savings.

## Service boundary

`--ephemeral` prevents local Codex session rollout persistence. It does not mean that the configured Codex service or model provider receives no task data. Harness has no remote telemetry of its own; service-side processing and retention follow the user's Codex account and provider policy.

The local store is not encrypted at rest, does not provide signed audit logs, and is not a regulatory compliance system.
