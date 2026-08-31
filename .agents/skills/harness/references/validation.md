# Validation

Read this reference after artifacts have been generated or updated.

## Structural checks

- Agent TOML parses and contains `name`, `description`, and `developer_instructions`.
- Every skill has valid frontmatter and a directory-matching name.
- Manifest paths stay inside the repository and all topology references resolve.
- The root instruction file has at most one complete managed block.
- The manifest points to the root instruction file Codex will actually load (`AGENTS.override.md` before `AGENTS.md`).
- Managed hashes match after generation.
- Manifest schema 5 declares journaled application with transaction schema 2.
- Every evidence object resolves to the recorded repository file hash, and optional line ranges remain valid.
- Material boundaries have topology-wide unique decision-area identifiers, persistence evidence, verifiable contracts, and material separation benefits.
- Persistent topology classification agrees with post-merge boundary structure and recurring coordination evidence.
- Task-execution state and runtime-only task risks are absent from the project manifest.
- Specialist and cross-boundary agents reference existing boundaries; `project-harness` alone uses project scope.
- Concurrent writers do not overlap, and sequential overlapping writers have an ordered verified handoff for their complete shared scope.
- Literal scopes do not authorize recursive descendants, and case-only writer scopes collide portably.
- Artifact, manifest, and transaction targets reject case-only collisions and file/child target conflicts before staging.
- Persistent quality policies have repository evidence, finite budgets, stopping conditions, and failure policies.
- Routing categories are globally unique, multi-category runtime matches cannot select conflicting routes implicitly, dependency shapes match relationship graphs, and coordination reasons have directly linked supporting topology.
- Required runtime capabilities have a probe declaration and a contract-preserving fallback. Live support remains a runtime check.
- Every Harness-owned complete file declares a valid permission mode; POSIX validation detects mode drift.
- No transaction journal or staging directory remains after a successful apply.
- Generated files contain no Claude-only or obsolete Agent Teams primitives.
- A clean plan dry-run reports the same create, update, or unchanged actions that the actual apply performs.

## Behavioral scenarios

Test the applicable cases, using an isolated temporary repository when possible:

1. A physically large single-boundary project remains minimal and produces no unnecessary specialist agent.
2. A composite project is divided by real responsibility, runtime, data, or contract boundaries.
3. A non-layered research, data, documentation, library, or CLI project does not acquire frontend/backend roles.
4. A same-language monorepo is divided only when package responsibilities justify it.
5. Existing root instructions survive managed-block insertion.
6. A user-modified managed file is preserved and reported.
7. A second run over unchanged inputs performs no file write or replacement.
8. Missing tools, post-freeze mutation, and non-retryable failures are surfaced.
9. An existing `AGENTS.override.md` receives the managed pointer instead of an inactive `AGENTS.md`.
10. A modified managed file makes both dry-run and apply refuse all writes.
11. A mid-apply failure restores updated files and removes files created by that transaction.
12. Recovery works even when interruption occurs before the journal records the last replaced path.
13. Recovery preserves an externally edited interrupted target and leaves the journal for manual resolution.
14. Four or more independent static boundaries may remain modular with an explicit review warning.
15. A minimal project's one-off destructive task may use coordinated runtime execution without changing the manifest topology.
16. Golden evaluation computes coverage from stable decision-area identifiers without semantic string similarity.
17. A modular expert pool remains modular even with four independent specialist boundaries.
18. A coordinated cross-contract fixture binds recurring reasons to patterns, phases, and a verified handoff.
19. Golden evaluation labels its topology-only scope and does not claim evidence validation.
20. Case-only artifact names and file/child output targets fail before a transaction journal is written.
21. A handoff covering only part of two writers' shared scope is rejected.
22. A coordinated full-plan fixture completes dry-run, journaled apply, manifest validation, and a no-op second apply.

## Completion gate

Validation succeeds only when every planned artifact is accounted for and structural checks pass. Clearly separate structural validation from a live Codex discovery or delegation smoke test, which may require restarting the session.

Follow [codex-smoke-test.md](codex-smoke-test.md) for a repeatable live check. Do not report structural validation as proof that Codex discovered or delegated to generated agents.
