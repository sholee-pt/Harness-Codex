# Orchestration

Read this reference before generating or updating `project-harness`.

## Choose the lightest execution shape

- Classify the current task as `direct`, `delegated`, or `coordinated` without changing the persistent project topology.
- Use direct execution for tightly coupled or small work.
- Use sequential delegation when later work depends on reviewed upstream output.
- Use parallel delegation only for independent scopes with a defined merge contract.
- Use persistent collaboration only when the current Codex runtime supports it and agents need repeated negotiation.
- Combine modes only when each phase has a clear boundary and a simpler shape is insufficient.
- Do not select coordinated execution from agent count, directory count, language count, or simple parallelism.

Use coordinated execution only when repeated findings can change another agent's work, expert judgments materially conflict, producer and reviewer require multiple rounds, cross-boundary agreement is required, runtime workload must be reassigned, or a reviewer chain must negotiate a phase freeze. One review pass remains delegated producer-reviewer. Read [teamplay-contract.md](teamplay-contract.md) for runtime roles, packets, adapter fallback, writer isolation, and retention. When delegation is selected, follow [native-subagent-relay.md](native-subagent-relay.md): spawn only selected project agents, wait for required results, validate parent-facing packets, relay material evidence to affected agents, and let the parent or integrator verify the final result.

Express orchestration in native Codex instructions. Do not emit Claude-specific tool syntax or depend on an unverified capability.

Persistent routing policies may recommend an execution class for evidence-backed task categories. Each category resolves to at most one route. When multiple categories match, use the route only if every match resolves to the same route; otherwise report the ambiguity and require an explicit runtime selection rather than merging policies or selecting the first route. When none matches, classify the current task from its scope and risk rather than assuming direct execution. The selected class, runtime-plan `participants`, and one-off task risks remain runtime state and are not written to the project manifest.

Separate collaboration patterns, which distribute work, from quality patterns, which challenge or check results. Every quality pattern must have a finite pattern-specific budget, a stopping condition, and a failure policy. Repository-default quality policies require structured evidence; one-off task-risk policies remain runtime-only.

## Required run protocol

For a small direct task, keep scope, outputs, and verification in the current task. Do not materialize a runtime-plan file, coordination packet, relay receipt, or disposable capability probe. Honor explicitly requested planning or auditing and required quality checks. Resolve routing ambiguity before taking this path. If later findings require delegation, validate the ephemeral plan before spawning. This clarification does not bypass generation/apply preflight or create a cache of live permissions and ownership checks.

1. Define the objective, completion criteria, scopes, planned artifacts, material assumptions, conflicting interpretations, simpler alternatives, and verification method before implementation.
2. Resolve the selected routing policy and probe required runtime capabilities before assignment. If a required capability is absent, select the declared fallback or stop that path. Static manifest validation does not prove live capability availability.
3. Give every delegated task an owner, input, output contract, write boundary, and verification method.
4. Collect explicit completion reports and account for every planned artifact.
5. Freeze phase outputs before downstream validation: record content hashes and tell earlier writers not to mutate them.
6. If a frozen input changes, invalidate dependent validation and rerun it against the new hash.
7. Integrate evidence in the primary agent and report omissions or conflicts.
8. Keep the validated runtime plan and workspaces ephemeral by default. Full-audit retention requires explicit user opt-in and disclosed purge terms.

## Failure classification

- Retry a clearly transient interruption at most once.
- Do not retry authentication, authorization, permission, quota, unsupported-tool, or invalid-input failures without a state change.
- Inspect partial artifacts before deciding whether work can continue.
- Mark every result as complete, partial, skipped, or failed. Plausible-looking output is not evidence that all branches completed.

## Generated orchestrator contents

The `project-harness` skill should contain the project-specific trigger, topology, task-routing rules, inputs and outputs, and the canonical contracts from the bundled template. Do not restate those contracts in a second generic run protocol. The builder adds concise direct-execution guidance without changing the required canonical v2 block. Keep detailed domain procedures in separate project skills and load delegation references only when that execution path is selected.
