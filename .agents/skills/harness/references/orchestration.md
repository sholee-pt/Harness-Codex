# Orchestration

Read this reference before generating or updating `project-harness`.

## Choose the lightest execution shape

- Classify the current task as `direct`, `delegated`, or `coordinated` without changing the persistent project topology.
- Use direct execution for tightly coupled or small work.
- Use sequential delegation when later work depends on reviewed upstream output.
- Use parallel delegation only for independent scopes with a defined merge contract.
- Use persistent collaboration only when the current Codex runtime supports it and agents need repeated negotiation.
- Combine modes only when each phase has a clear boundary and a simpler shape is insufficient.

Express orchestration in native Codex instructions. Do not emit Claude-specific tool syntax or depend on an unverified capability.

Persistent routing policies may recommend an execution class for evidence-backed task categories. The selected class, active agent list, and one-off task risks remain runtime state and are not written to the project manifest.

Separate collaboration patterns, which distribute work, from quality patterns, which challenge or check results. Every quality pattern must have a finite pattern-specific budget, a stopping condition, and a failure policy. Repository-default quality policies require structured evidence; one-off task-risk policies remain runtime-only.

## Required run protocol

1. Define the objective, completion criteria, scopes, and planned artifacts.
2. Resolve the selected routing policy and probe required runtime capabilities before assignment. If a required capability is absent, select the declared fallback or stop that path. Static manifest validation does not prove live capability availability.
3. Give every delegated task an owner, input, output contract, write boundary, and verification method.
4. Collect explicit completion reports and account for every planned artifact.
5. Freeze phase outputs before downstream validation: record content hashes and tell earlier writers not to mutate them.
6. If a frozen input changes, invalidate dependent validation and rerun it against the new hash.
7. Integrate evidence in the primary agent and report omissions or conflicts.

## Failure classification

- Retry a clearly transient interruption at most once.
- Do not retry authentication, authorization, permission, quota, unsupported-tool, or invalid-input failures without a state change.
- Inspect partial artifacts before deciding whether work can continue.
- Mark every result as complete, partial, skipped, or failed. Plausible-looking output is not evidence that all branches completed.

## Generated orchestrator contents

The `project-harness` skill should contain the project-specific trigger, topology, task-routing rules, inputs and outputs, phase boundaries, capability fallback, freeze protocol, verification, and safe stopping conditions. Keep detailed domain procedures in separate project skills.
