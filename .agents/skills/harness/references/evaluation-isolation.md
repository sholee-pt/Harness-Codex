# Paired Evaluation Isolation

`paired-run` compares a baseline without Harness-managed agents, skills, and instruction block against a treatment with the clean Harness installation.

## Preconditions

- clean Git repository;
- two detached temporary worktrees from one commit;
- user-owned project instructions, source, tests, agents, and skills preserved in both arms;
- dedicated `CODEX_HOME` with no global instructions, Harness skill, or comparison-changing config;
- one prompt fingerprint, model, reasoning effort, sandbox, network policy, timeout, verification profile, and evaluator version;
- predeclared Comparison Plan Schema 1; and
- randomized or counterbalanced arm order with the seed recorded.

Codex builds global and project instruction chains independently on every run. Merely deleting `.codex/agents` is not a valid baseline.

## Verification profile

The profile is a user-approved JSON file with a non-shell argument array. The record stores only its digest, pseudonymous check reference, kind, result, and exit code.

## Failure handling

Timeout handling terminates the process group, confirms exit, and rechecks the worktree before claiming complete isolation. A missing check, surviving process, mismatched prompt, model, source snapshot, sandbox, or verification profile downgrades isolation.

Partial or failed isolation may be retained as paired replay evidence but cannot be promoted to a controlled live comparison.
