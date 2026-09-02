# Runtime Teamplay Recipes

Use these recipes as decision examples, not persistent templates. Every plan remains bound to the current manifest and task.

## Independent research fan-out/fan-in

- Choose when investigations are independent and have a defined synthesis contract; do not choose when each finding repeatedly changes the other investigations.
- Roles: scouts and one integrator. Graph: parallel collection, then synthesis.
- Messages: material findings and completion packets. Writers: normally none.
- Verify source coverage and synthesis criteria. Stop after every branch reports complete, partial, skipped, or failed.
- Fallback: sequential collection. Retention: ephemeral.

## Producer-reviewer code change

- Choose delegated execution for one independent review pass; choose coordinated only for bounded repeated correction rounds.
- Roles: isolated writer producer, read-only reviewer, primary integrator.
- Graph: implement, freeze diff/hash, review, integrate, verify.
- Messages: handoff, challenge, decision, complete. The producer alone owns its write scope.
- Stop after acceptance or the declared review budget; unresolved critical findings fail.
- Fallback: sequential frozen diff review. Retention: ephemeral.

## Cross-contract migration

- Choose coordinated when API, schema, storage, or file-format owners must negotiate a compatible contract; do not choose for a one-sided mechanical update.
- Roles: boundary producers/reviewers and one integrator. Graph: inspect, propose, cross-review, integrate, migrate, verify.
- Messages: findings, evidence-backed challenges, handoffs, decisions, completion.
- Writers use separate worktrees and disjoint scopes; ordered overlap needs a complete frozen handoff.
- Verify every contract and migration. Missing required artifacts or unresolved critical challenges stop the run.
- Fallback: leader relay with sequential handoffs. Retention: ephemeral or explicitly redacted.

## Supervisor-based large migration

- Choose only when runtime workload must be reassigned; do not choose merely because many files exist.
- Roles: supervisor, bounded writers, read-only verifiers, integrator. Graph: staged work packages with finite reassignment.
- Messages: blockers, reassignment decisions, handoffs, completion. Only the supervisor reassigns.
- Verify every package and final integration. Stop at the reassignment budget or a critical scope violation.
- Fallback: fixed delegated batches under leader control. Retention: redacted only when operational history is useful.

## Direct small fix

- Choose for a small tightly coupled edit with no material delegation benefit.
- Role: primary agent. Graph: reproduce, edit, verify.
- No team messages or secondary write scopes.
- Stop after the stated verification or report the exact uncertainty.
- Fallback: none needed. Retention: ephemeral.

## Provisional greenfield design

- Choose only as a temporary runtime design aid when repository evidence is absent; do not persist the domain brief as a material boundary.
- Roles use provisional runtime participant IDs. Graph: brief, competing constraints, reviewed architecture, initial artifacts.
- Messages: findings, challenges, decisions, completion. Writes remain bounded to the agreed initial artifact scopes.
- Verify artifact consistency, then run normal evidence analysis after files exist.
- Stop without persistent promotion. Fallback: direct design with explicit assumptions. Retention: ephemeral.

## Hybrid collection, synthesis, and verification

- Choose when independent evidence collection is followed by reciprocal synthesis and then independent verification; do not mix modes without phase boundaries.
- Roles: delegated scouts, coordinated domain reviewers/integrator, delegated read-only verifier.
- Graph: fan-out collection, frozen collection handoff, coordinated synthesis, frozen decision, independent verification.
- Messages are limited to material findings in collection, challenges/decisions in synthesis, and completion in verification.
- Verify phase hashes and invalidate downstream checks when an upstream hash changes.
- Fallback: sequential collection and leader-relay synthesis. Retention: ephemeral.
