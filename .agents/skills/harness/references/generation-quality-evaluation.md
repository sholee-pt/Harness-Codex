# Independent generation quality evaluation

Use only when asked to evaluate the generator or when a maintainer is validating a change to its guidance. This is an evaluation protocol, not a normal generation requirement or an automatic optimization loop.

Separate three questions:

1. **Materialization:** does a fixed authoring draft build, apply, validate and repeat without unintended writes? Existing deterministic fixtures answer this.
2. **Generation quality:** does a fresh agent, given raw project evidence and a realistic short request, choose defensible responsibilities, scopes and procedures? Replaying an authored draft does not answer this.
3. **Use and benefit:** does a fresh native session discover the result, carry out a real task, and improve a measured outcome under comparable conditions? A valid plan or a successful discovery probe does not answer all three.

## Generation comparison

Use isolated small project copies, including a non-model control so conditional ML guidance can be checked for overuse. Include projects and tasks not used to write the new guidance. Preserve user instructions, source and runtime settings equally across comparison arms. Record model, reasoning settings, runtime version, input identities, authoring prompt, guidance revision and every attempted run. Bound attempts before running them; retain invalid and incomplete drafts in the denominator rather than quietly retrying until a good example appears.

Give the generating agent the actual request, relevant skill and raw fixture. Do not supply expected role names, intended topology, a worked plan, suspected issues or the review rubric. Have a reviewer who did not author that run assess the result against a rubric established from source contracts and held-out task requirements. Hide the arm label where practical. An independent pass using the same model is useful procedural separation, not independent scientific ground truth.

Score concrete observations separately: unsupported responsibilities; missed required interfaces; overlapping writer ownership; unowned requested work; unnecessary delegation; relevant verification and experiment contracts; unsupported claims; generation/apply completion. Do not require a fixed number of agents or reward extra checklist length. Record disagreements and reviewer rationale instead of presenting a single invented quality score.

## Native task follow-through

When evaluating external-procedure or domain guidance, include a small CLI fix with no scientific work; an existing relevant external skill that should not be duplicated; a single-cell project with mismatched count/feature contracts; repeated measurements that cannot be treated as independent samples; an experiment comparison with missing/duplicate runs; and an API rename whose consumer still uses the old field. Vary domains beyond these examples and include held-out raw projects. Assess missed contracts and unnecessary procedure/team expansion independently. These are proposed evaluation cases, not evidence that a fresh-generation trial has run.

Use [codex-smoke-test.md](codex-smoke-test.md) for fresh-session discovery and observed delegation. Include a small direct task, a justified specialist task and, if applicable, a producer-reviewer task. Verify changed files and project-native outcomes, not only the final explanation. Separate automatic selection from an explicitly named agent test; both are useful but prove different things.

Compare task results only with an uncontaminated baseline and fixed task/verification/runtime conditions. The existing `paired-run` evaluator addresses downstream use of an already generated harness and has its own [isolation requirements](evaluation-isolation.md); it is not a fresh-generation evaluator and does not support every workspace layout. Do not expand its accepted source contract or weaken isolation to make a generation study fit.

Report static instruction bytes separately from observed loading, input/cached/output tokens, elapsed time and rework. Missing usage stays unknown. Separate parent-only counters from aggregate parent-and-child usage when the runtime exposes them. A short successful example is neither a token-saving measurement nor proof of general routing accuracy. Keep experimental raw artifacts in the explicitly selected isolated evidence directory; never ingest them into enum-only operations records or publish private project data by default.
