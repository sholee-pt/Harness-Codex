# Paired Evaluation Isolation

`paired-run` compares a baseline without Harness-managed agents, skills, and instruction block against a treatment reconstructed from a verified local-only Harness installation.

## Preconditions

- clean Git repository containing a valid current-version local-only Harness installation;
- exactly one registered source worktree, so reading and checking the source `info/exclude` has unambiguous scope;
- an exact bounded in-memory snapshot of the manifest, every manifest-managed file, and every manifest-referenced evidence file, including file modes;
- two independent temporary local clones from one commit, each with its own Git metadata, no retained remote, and one registered worktree;
- user-owned project instructions, source, tests, agents, and skills preserved in both arms;
- dedicated `CODEX_HOME` with no global instructions, Harness skill, or comparison-changing config;
- a distinct temporary user home for each arm, with no authentication or configuration copied from the caller's home;
- no known Harness skill under that user home, its compatibility path, the dedicated `CODEX_HOME`, or a readable POSIX admin skill root;
- one prompt fingerprint, model, reasoning effort, sandbox, network policy, timeout, verification profile, and evaluator version;
- Comparison Plan Schema 2 supplied and validated before either arm executes, with an intervention and task stratum; and
- randomized or counterbalanced arm order with the seed recorded.

Codex builds global and project instruction chains independently on every run. Merely deleting `.codex/agents` is not a valid baseline.

Before either arm starts, Harness validates the source installation, confirms that no transaction is pending, and verifies the source commit, clean Git status, worktree count, manifest bytes, and captured managed and evidence bytes. Snapshot size and file count are bounded. Unknown ignored or untracked project content is deliberately not copied, but ignored or untracked files explicitly referenced by the manifest are classified and materialized with exact bytes and modes in both arms. Every evidence target in both arms is preflighted before the first write; lexical symlink or Windows reparse-point ancestors, directory collisions, and managed/evidence namespace overlap fail closed. Tracked evidence is overwritten from the snapshot to neutralize checkout conversion.

Harness then removes its managed state from the baseline and installs the verified managed snapshot with a clone-local exclusion block in the treatment. A generated-only instruction file is deleted from the baseline rather than retained as framing whitespace. When a managed instruction also contains user content but its pre-install bytes are not available, the remainder is preserved and `baseline-instruction-provenance-unavailable` makes the comparison partial. This does not cover tracked user instructions, which normal generation protects through `explicit-skill` instead of a managed pointer. A legacy empty user instruction that is byte-identical to a generator-created file cannot be distinguished without a future provenance contract.

Immediately before synthetic task-base creation, Harness checks equal evidence bytes and modes, absence of baseline Harness state, full treatment validation, source-commit identity, no retained clone remotes, no unexpected changed project paths, and equal normalized user-instruction remainders. Task-base creation advances `HEAD` without re-checking files through platform line-ending conversion, and evidence is verified again before Codex starts.

## Verification profile

The profile is a user-approved JSON file with a non-shell argument array. The record stores only its digest, pseudonymous check reference, kind, result, and exit code. Verification must not change repository content, `HEAD`, symbolic `HEAD`, index entries, or porcelain status. Harness measures the task fingerprint and patch scope immediately after Codex exits, captures the pre-verification repository-state signature, runs verification in a dedicated process group, confirms cleanup, and captures two matching post-verification signatures across a bounded quiescence interval. A changed or non-quiescent repository is retained with `partial` comparability and `verification-repository-state-mutated`; an unavailable measurement uses `verification-repository-state-unavailable`. A cleanup failure uses `verification-process-cleanup` and failed isolation. None of these cases can support concrete attribution.

## Failure handling

Success, failure, and timeout handling all invoke process-group cleanup before the quiescence check. POSIX cleanup terminates the complete process group and confirms that it is gone. Windows uses `CTRL_BREAK_EVENT` and `taskkill /T /F`; complete Windows isolation remains receipt-gated. A process that deliberately detaches into a different process group may evade direct group cleanup, so the bounded quiescence check provides an additional repository-state safeguard rather than an unlimited guarantee. A known user/admin Harness skill, missing check, surviving process, mismatched prompt, model, Codex version, platform, capture mode, source snapshot, sandbox, or verification profile downgrades isolation. A dedicated `CODEX_HOME` containing instructions, configuration, or a Harness skill is rejected before execution.

On Windows, complete live isolation additionally requires a user-local JSON receipt whose implementation digest matches the current process-tree cleanup function. Without it, the run is retained with `windows-process-tree-unverified` and partial isolation. The receipt is support evidence, not project state, and is never copied into the target repository.

Each arm is committed to a clean synthetic pre-task commit after baseline/treatment preparation. Both Run records retain the original user commit as `sourceSnapshotId`, while result fingerprinting and patch-scope evaluation compare the post-task state with that arm-specific internal base. The internal base is not added to Run Record Schema 2. Default `--dry-run` performs source preflight without cloning, invoking Codex, or writing evaluation state, and therefore reports clone/materialization observations as not performed or unavailable. `--dry-run --validate-materialization` creates and discards both clone arms, validates their materialization and task bases, and reports the observed no-remote state without invoking Codex or writing evaluation state.

Partial or failed isolation may be retained as paired replay evidence but cannot contribute Proposal support statistics or concrete attribution. A task outcome failure under complete comparability remains valid harmful evidence when the planned outcome measurement is available.
