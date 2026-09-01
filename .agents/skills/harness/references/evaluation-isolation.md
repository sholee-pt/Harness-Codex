# Paired Evaluation Isolation

`paired-run` compares a baseline without Harness-managed agents, skills, and instruction block against a treatment with the clean Harness installation.

## Preconditions

- clean Git repository;
- two detached temporary worktrees from one commit;
- user-owned project instructions, source, tests, agents, and skills preserved in both arms;
- dedicated `CODEX_HOME` with no global instructions, Harness skill, or comparison-changing config;
- a distinct temporary user home for each arm, with no authentication or configuration copied from the caller's home;
- no known Harness skill under that user home, its compatibility path, the dedicated `CODEX_HOME`, or a readable POSIX admin skill root;
- one prompt fingerprint, model, reasoning effort, sandbox, network policy, timeout, verification profile, and evaluator version;
- Comparison Plan Schema 2 supplied and validated before either arm executes, with an intervention and task stratum; and
- randomized or counterbalanced arm order with the seed recorded.

Codex builds global and project instruction chains independently on every run. Merely deleting `.codex/agents` is not a valid baseline.

## Verification profile

The profile is a user-approved JSON file with a non-shell argument array. The record stores only its digest, pseudonymous check reference, kind, result, and exit code. Verification must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status. Harness measures the task fingerprint and patch scope immediately after Codex exits, captures the pre-verification repository-state signature, runs verification in a dedicated process group, confirms cleanup, and captures two matching post-verification signatures across a bounded quiescence interval. A changed or non-quiescent repository is retained with `partial` comparability and `verification-repository-state-mutated`; an unavailable measurement uses `verification-repository-state-unavailable`. A cleanup failure uses `verification-process-cleanup` and failed isolation. None of these cases can support concrete attribution.

## Failure handling

Success, failure, and timeout handling all invoke process-group cleanup before the quiescence check. POSIX cleanup terminates the complete process group and confirms that it is gone. Windows uses `CTRL_BREAK_EVENT` and `taskkill /T /F`; complete Windows isolation remains receipt-gated. A process that deliberately detaches into a different process group may evade direct group cleanup, so the bounded quiescence check provides an additional repository-state safeguard rather than an unlimited guarantee. A known user/admin Harness skill, missing check, surviving process, mismatched prompt, model, Codex version, platform, capture mode, source snapshot, sandbox, or verification profile downgrades isolation. A dedicated `CODEX_HOME` containing instructions, configuration, or a Harness skill is rejected before execution.

On Windows, complete live isolation additionally requires a user-local JSON receipt whose implementation digest matches the current process-tree cleanup function. Without it, the run is retained with `windows-process-tree-unverified` and partial isolation. The receipt is support evidence, not project state, and is never copied into the target repository.

Each arm is committed to a clean synthetic pre-task commit after baseline/treatment preparation. Both Run records retain the original user commit as `sourceSnapshotId`, while result fingerprinting and patch-scope evaluation compare the post-task state with that arm-specific internal base. The internal base is not added to Run Record Schema 2.

Partial or failed isolation may be retained as paired replay evidence but cannot contribute Proposal support statistics or concrete attribution. A task outcome failure under complete comparability remains valid harmful evidence when the planned outcome measurement is available.
