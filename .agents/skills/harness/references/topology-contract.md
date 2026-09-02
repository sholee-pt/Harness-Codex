# Topology Contract

Read this reference after repository profiling and before writing a schema 3 plan.

## Persistent topology versus runtime execution

The manifest records persistent repository structure:

- `minimal`: zero or one material boundary and no recurring coordination;
- `modular`: two or more material boundaries with static selection or handoffs;
- `coordinated`: repository evidence proves recurring dynamic allocation, fan-out/fan-in, cross-contract verification, reviewer chains, or phase freezing.

Boundary count is not a coordinated-topology trigger. Four or more modular boundaries produce a review warning, not an automatic promotion. Current-task risk changes only runtime execution (`direct`, `delegated`, or `coordinated`) and must not appear in the generation plan or project manifest.

Persistent collaboration patterns describe recurring repository structure, not a currently active team. Even a persistent `coordinated` topology requires current-task interaction value and a live capability probe before coordinated execution. Runtime roles, participants, task graphs, messages, adapter selection, retention, and provisional greenfield roles belong only to an ephemeral runtime plan and are not agent components or manifest fields.

## Material boundary

Every retained boundary must include:

- a unique kebab-case `id` and one or more topology-wide unique, stable `decisionAreaIds`;
- one or more types from `responsibility`, `execution-environment`, `contract`, `data-flow`, `quality-risk`, and `recurring-workflow`;
- structured repository evidence;
- concrete inputs, outputs, contracts, or read/write scopes;
- verification and failure impact;
- persistent-project evidence classified as `stable-structure`, `documented-recurring-workflow`, or `historically-observed`;
- at least one material separation benefit;
- acyclic execution dependencies in `dependsOn` and non-ordering structural relationships in `interactsWith`.

Use `overlapWith` only when two retained boundaries share material inputs, decisions, outputs, or scopes. Such a boundary requires a `separationRationale` with distinct decisions and failure modes. Record removed candidates in `classification.mergedCandidates`; `materialBoundaryCount` is the retained post-merge count.

`dependencyShape` must agree with the relationship graph. `independent` has no `dependsOn` edges, `cyclic-contract` has a cycle in `interactsWith`, and `dynamic` uses coordinated topology with the `dynamic-allocation` reason. `static-dag` summarizes the acyclic execution graph and may coexist with non-ordering structural interaction cycles; select `cyclic-contract` when such a cycle is the material topology driver. Coordination reasons must also have supporting structure: fan-out/fan-in declares its collaboration pattern, cross-contract verification has a component, policy, or handoff that actually references at least two contract boundaries, reviewer chains use producer-reviewer collaboration with ordered phases, and phase freezing has ordered lanes plus a verified handoff.

Evidence hashes bind a claim to inspected bytes. They do not prove the semantic truth of the claim. Review the claim and persistence conclusion before apply.

## Agent and skill scope

- A specialist agent or skill uses `scope: boundary` and exactly one `boundaryRefs` entry.
- A cross-boundary agent or skill uses `scope: cross-boundary` and at least two references.
- The `project-harness` skill alone uses `scope: project` and omits boundary references.
- A material boundary does not require a dedicated agent. Generate an agent only when delegation has a concrete benefit.

## File access lanes

File scopes are either normalized literal POSIX-relative paths or directory prefixes ending in `/**`. Other wildcards are unsupported. A literal scope authorizes only that exact path and cannot contain a recursive scope with the same base. Recursive scopes contain the base path and its descendants. Writer overlap comparison is case-insensitive on every platform so a plan cannot hide a Windows collision behind case-only differences.

Each execution phase has a non-negative order and one or more concurrency groups, each with its own order. An agent file-access entry references one phase and one group:

```json
{
  "scope": "src/model/**",
  "mode": "write",
  "phase": "implementation",
  "concurrencyGroup": "parallel-build"
}
```

Two writers in the same lane may not use overlapping scopes. Writers in different ordered lanes may overlap only when a directional handoff names both agents, both lanes, their complete shared scope, a freeze precondition, and verification. A handoff for only a descendant of the shared scope is insufficient. Producer-write/reviewer-read overlap is allowed.

## Collaboration and quality policies

`collaborationPatterns` describe work distribution. `qualityPatternPolicies` describe how results are challenged or checked. Persistent quality policies require:

- `justificationSource: repository-evidence`;
- structured evidence and material-boundary references;
- a finite pattern-specific budget;
- a stopping condition;
- a failure policy.

Runtime-only task risks and their selected quality patterns are not persistent topology state.

Each quality pattern accepts only its own budget keys: adversarial verification uses `maxAgents` and `maxRounds`; judge panel uses `maxCandidates` and `maxJudges`; loop-until-dry uses `maxRounds` and `zeroFindingRounds`; multi-angle sweep uses `maxAngles`; completeness critic uses `maxRounds`; and independent safety review uses `maxReviewers`. For loop-until-dry, `zeroFindingRounds` cannot exceed `maxRounds`.

## Capability policies

Capability policies express semantic intent independently of a changing runtime. Direct instruction-driven execution may require no special capability. A policy that requires runtime capabilities or prefers runtime-native mapping must declare a runtime probe and a fallback that preserves input, output, and verification contracts.

Static validation proves that the declaration is complete. Actual capability availability is checked at task execution time.

Harness for Codex v5+ does not add a persistent model-selection policy. Generated agents inherit the active model by default. A model override remains an explicitly reviewed runtime-specific choice and must not be used merely to signal role importance.

## Routing policies

Persistent routing policies describe evidence-backed task categories and refer only to existing boundaries, declared collaboration patterns, quality policies, and capability policies. A task category belongs to at most one route. A direct route cannot declare collaboration patterns. Multiple matching categories may select one route only when all matches resolve to that same route; conflicting matches are reported as ambiguous and require an explicit runtime choice. If no persistent route matches, classify the current task at runtime; do not assume direct execution. Routes recommend an execution class but do not persist the current request's selected class or agent list.

## Deterministic evaluation boundary

Golden evaluation compares stable IDs, counts, enums, and references. It does not use semantic string similarity. Its output declares `validationScope: topology-contract` and `evidenceValidated: false`. A deterministic fixture proves that a proposed plan satisfies the topology contract; it does not prove that evidence files or hashes are current and does not prove that an LLM will infer the same plan from an arbitrary repository. Run `harness_apply.py --dry-run` for evidence and ownership validation. Live discovery and generation-quality evaluation remain separate runtime checks.
