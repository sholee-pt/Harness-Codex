# Validation

Read this reference after artifacts have been generated or updated.

## Structural checks

- Agent TOML parses and contains `name`, `description`, and `developer_instructions`.
- Every skill has valid frontmatter and a directory-matching name.
- Manifest paths stay inside the selected workspace and all topology references resolve.
- The root instruction file has at most one complete managed block.
- Managed-pointer mode points to the root instruction file Codex will actually load (`AGENTS.override.md` before `AGENTS.md`); explicit-skill mode has no managed pointer and preserves the user's instruction file.
- Manifest Schema 7 records project-local scope, selected workspace kind, instruction activation, and `not-managed` Git protection with empty patterns.
- Managed hashes match after generation.
- Manifest Schema 7 declares journaled application with Transaction Schema 2; generation never modifies Git metadata.
- Every evidence object resolves to the recorded repository file hash, and optional line ranges remain valid.
- Material boundaries have topology-wide unique decision-area identifiers, persistence evidence, verifiable contracts, and material separation benefits.
- Persistent topology classification agrees with post-merge boundary structure and recurring coordination evidence.
- Task-execution state and runtime-only task risks are absent from the project manifest.
- Runtime plans, participants, roles, tasks, messages, adapter selection, and retention are absent from the project manifest.
- Specialist and cross-boundary agents reference existing boundaries; `project-harness` alone uses project scope.
- Concurrent writers do not overlap, and sequential overlapping writers have an ordered verified handoff for their complete shared scope.
- Literal scopes do not authorize recursive descendants, and case-only writer scopes collide portably.
- Artifact, manifest, and transaction targets reject case-only collisions and file/child target conflicts before staging.
- Persistent quality policies have workspace evidence, finite budgets, stopping conditions, and failure policies.
- Routing categories are globally unique, multi-category runtime matches cannot select conflicting routes implicitly, dependency shapes match relationship graphs, and coordination reasons have directly linked supporting topology.
- Required runtime capabilities have a probe declaration and a contract-preserving fallback. Live support remains a runtime check.
- Every Harness-owned complete file declares a valid permission mode; POSIX validation detects mode drift.
- No transaction journal or staging directory remains after a successful apply.
- Generated files contain no Claude-only or obsolete Agent Teams primitives.
- A clean plan dry-run reports the same create, update, or unchanged actions that the actual apply performs.
- A runtime plan is bound to the exact current manifest and canonical topology, references only allowed persistent agents or explicitly provisional participants, and does not modify either file.
- Coordinated runtime plans have finite communication and reassignment budgets, evidence-backed challenges, stopping conditions, capability fallback, isolated writers, and ephemeral retention by default.
- Draft plans materialize every deterministic change-discipline, teamplay, and topology-derived agent contract exactly once before apply checks the Schema 3 plan and Artifact Contract 2.
- Runtime receipts reject invalid receiver/control-plane state, duplicate spawns, verified role/parent/session-source contradictions, and exhausted or inconsistent fixed wait budgets. Unregistered event profiles are unsupported; malformed or unknown event structures degrade evidence. Missing optional evidence alone is not a verified conflict.
- Relay receipts bind reviews to input packet hashes, invalidate stale reviews, and account for exactly the affected agents without changing Coordination Packet Schema 1.
- Builder, apply, and installed-state validation accept selected Git-contained folders, nested independent repositories, and linked worktrees while rejecting paths outside the selected root.
- Authoring Contract 3 drafts materialize to Schema 3 plans with Artifact Contract 2 and cannot reach apply with the draft-only version field intact.
- Skill metadata uses the shared strict string parser, and decoded agent instructions match the topology-derived block; arbitrary prose is not semantically verified.
- Clean recognized v7 and v8 installations report `upgrade-required`; corruption and incomplete current or required legacy contracts remain `invalid`.
- Current Git protection is `not-managed` with no patterns, regardless of workspace layout. Existing Git metadata and prior exclusion markers remain unchanged.

## Behavioral scenarios

Select scenarios from the changed behavior; a small edit does not require this entire list. Stateful changes may need interruption/resume, stale state, concurrent ownership, dirty user files, timeout and false-completion probes. Keep the existing retry/revision budgets. Repeating the same failure without a new hypothesis or changed evidence is a reason to report the blocker, not weaken a check or start an unbounded repair loop.

Test the applicable cases, using an isolated temporary repository when possible:

1. A physically large single-boundary project remains minimal and produces no unnecessary specialist agent.
2. A composite project is divided by real responsibility, runtime, data, or contract boundaries.
3. A non-layered research, data, documentation, library, or CLI project does not acquire frontend/backend roles.
4. A same-language monorepo is divided only when package responsibilities justify it.
5. Existing root instructions survive managed-block insertion.
6. A user-modified managed file is preserved and reported.
7. A second run over unchanged inputs performs no file write or replacement.
8. Missing tools, post-freeze mutation, and non-retryable failures are surfaced.
9. Existing user text outside the appended root activation block remains byte-identical; a clean Harness-owned pointer block may be updated independently of tracking. Legacy explicit-skill state remains readable.
10. Generating inside a Git workspace leaves Git metadata unchanged and does not promise clean status or automatic exclusion.
11. A plain directory workspace needs no Git executable or remote and a non-Git directory workspace may preserve nested repositories as boundaries.
12. A modified managed file makes both dry-run and apply refuse all writes.
13. A mid-apply failure restores updated files and removes files created by that transaction.
14. Recovery works even when interruption occurs before the journal records the last replaced path.
15. Recovery preserves an externally edited interrupted target and leaves the journal for manual resolution.
16. Four or more independent static boundaries may remain modular with an explicit review warning.
17. A minimal project's one-off destructive task may use coordinated runtime execution without changing the manifest topology.
18. Golden evaluation computes coverage from stable decision-area identifiers without semantic string similarity.
19. A modular expert pool remains modular even with four independent specialist boundaries.
20. A coordinated cross-contract fixture binds recurring reasons to patterns, phases, and a verified handoff.
21. Golden evaluation labels its topology-only scope and does not claim evidence validation.
22. Case-only artifact names and file/child output targets fail before a transaction journal is written.
23. A handoff covering only part of two writers' shared scope is rejected.
24. A coordinated full-plan fixture completes dry-run, journaled apply, manifest validation, and a no-op second apply.
25. Materially ambiguous requirements surface the competing interpretations instead of selecting one arbitrarily.
26. A one-line function change uses direct execution without unnecessary agents, skills, or abstractions.
27. A file-scoped bug fix avoids unrelated files and formatting changes.
28. A reproducible bug defines the reproducer or explicit verification criteria before implementation.
29. Two available agents alone do not select coordinated execution.
30. Independent tasks select delegated fan-out/fan-in; one review pass selects delegated producer-reviewer; repeated cross-boundary negotiation may select coordinated execution.
31. A stale runtime plan, unknown agent, dependency cycle, unowned required output, reviewer write scope, or missing required verification is rejected without changing the manifest.
32. Parallel Codex delegation selects parent-relayed subagents; lack of delegation selects a sequential or direct contract-preserving fallback.
33. A returned coordination packet is rejected for wrong task ownership, missing evidence, missing required outputs, unverified completion, or changed paths outside the participant's write scope.
34. Structural and packet validation remain distinct from an optional live smoke test; neither validator claims that a subagent actually ran.
35. Ephemeral retention is the default; full audit requires explicit user opt-in and redacted retention stores no raw messages.
36. Missing or duplicate deterministic placeholders fail before apply; a correct builder output remains an ordinary valid Schema 3 plan.
37. A missing or unlisted canonical receiver handle, wait on an unknown handle, exhausted wait budget, agent-reported-only result, or verified terminal/binding contradiction cannot be reported as observed completion. Missing optional public or local evidence lowers evidence strength without stopping a valid bounded handle wait.
38. Runtime Receipt Schema 2 marks an unregistered event profile as unsupported; the CLI version is provenance rather than an allowlist. It reports malformed or unknown structures as degraded; absence alone is not a conflict. An exact profile contradiction, verified binding mismatch, or incompatible terminal outcome fails closed, while raw prompts, messages, paths, IDs, handles, task names, and credentials never enter a receipt.
39. A review bound to an older packet hash is stale after revision, and rerun accounting rejects both missing affected agents and unrelated reruns.
40. Main and linked worktrees both support generation without modifying their shared Git metadata.
41. Portable path checks reject traversal, case aliases, controls, and symlink or junction escapes before writes.
42. A transaction failure restores project files according to the journal contract while Git metadata remains unchanged.
43. An external edit to a managed file blocks apply and preserves the edit.
44. A legacy Harness exclusion marker without a manifest is preserved and does not block generation.
45. Project generator install is a dry-run-safe copy with a separate receipt, safe updates, unchanged-content no-op, user-file preservation, and failed-promotion rollback.

## Completion gate

The `activation` report distinguishes a structurally configured managed pointer from explicit skill activation. `runtimeLoaded` remains `not-tested` for both. Invalid installations report blocked activation and no recommended invocation until errors are resolved. `harness_doctor.py --root WORKSPACE` combines these checks with environment diagnostics without launching Codex or writing the workspace.

Validation succeeds only when every planned artifact is accounted for and structural checks pass. Clearly separate structural validation from a live Codex discovery or delegation smoke test. Codex detects skill changes automatically; when new custom agents, a new skill, or a newly created root pointer is not active, start one fresh task in the same workspace rather than deleting tasks or restarting after each request.

`validate_harness.py` reports static `validationLayers` separately from `externalCapabilities`. A green static report covers transaction state, selected-root context, manifest shape, evidence freshness, topology/artifact contracts, managed ownership, and runtime-state separation. `customAgentDiscovery` and `liveDelegation` remain `not-tested`, while task correctness and Harness benefit attribution remain `not-measured`, until their separate evidence-producing workflows run.

Follow [codex-smoke-test.md](codex-smoke-test.md) for a repeatable live check. Do not report structural validation as proof that Codex discovered or delegated to generated agents.
