# Optional Jev retrieval advice

Jev can classify candidates already returned by a Graft query. Successful `init`
automatically enables its shadow comparison after Graft is ready. It requires a
separate TypeSafe API key for actual requests; init itself makes no Jev API calls.

Initialize normally; no separate `jev enable` command is needed:

```bash
# Set TYPESAFE_API_KEY through your own shell or secret manager first.
harness-codex init --project /path/to/project
harness-codex graft query "Where is request validation implemented?" --project /path/to/project --json
harness-codex jev status --project /path/to/project --json
```

This requires a TypeSafe account/key independently of Codex authentication.
Without a key, Jev remains configured and Graft returns its ordinary results.
Setting `TYPESAFE_API_KEY` later enables eligible calls without another init or
enable command. Init reports this condition and the external processing boundary.
The key is read from the environment, never saved in Harness settings or passed
on the process command line. Requests use the fixed HTTPS TypeSafe endpoint;
redirects are rejected. The provider receives the query and up to 2,400 characters
per returned candidate, including source pointers and code excerpts. Its data
handling policies apply. No full conversation, graph or extra source files are
sent. Do not enable this for projects whose retrieved source cannot be shared.
Use `init --retrieval off` to skip both retrieval setups, or run `jev disable`
after init to retain local Graft without Jev. No model request occurs in between
unless you run an eligible retrieval query. Existing Jev preferences, including
explicit disable/clear, mode, model, budgets, caches and labels, survive repeated
init without writes. `jev enable` explicitly re-enables a disabled setup. Config
and reset preserve Jev preferences. Dry-run, install-only, failed configuration
and disabled/unavailable Graft never initialize Jev.

## Selective calls and preserved behavior

- Only an actual `graft query` can call Jev. Init, configuration, ordinary turns,
  the native Auto model selector, status and disabled retrieval do not call it.
- A query needs 6-20 distinct candidates, a 20-8,000-character question and a
  request body no larger than 48,000 bytes. These are conservative eligibility
  rules, not proof that a judgment is necessary or beneficial.
- One request batches all candidate judgments. There are no per-candidate calls,
  generation calls or retries on the request path. The default ceiling is 20
  attempted calls per project per UTC day; `--daily-calls` accepts 1-100. Separate
  projects have separate limits, so this is not an account-wide spending cap.
- The child process has a four-second total deadline. A failed call reserves its
  budget and starts a five-minute cooldown. Missing keys, invalid responses,
  unavailable state, occupied locks and exhausted budgets preserve normal results.
- Identical query, candidates, policy and pinned model reuse advice for 24 hours.
  Changed snippets or model versions invalidate reuse. At most 128 entries remain.
  No graph refresh is added by Jev; Graft keeps its own source-change check.

The default **shadow** mode returns exactly the original Graft text. JSON also
contains `jev.queryId`, `suggestedOrder` and yes/no/abstain judgments. Candidate
`c0` is original hit 1, `c1` is hit 2, and so on. Probabilities at least 0.8 become
yes, at most 0.2 become no, and the middle band abstains. These thresholds are
policy heuristics, not calibrated accuracy. A negative answer never removes a hit.

After comparing suggestions with source inspection, optionally expose a reading
order hint to the agent:

```bash
harness-codex jev enable --project /path/to/project --mode suggest --daily-calls 20
```

Suggest mode adds one compact hint when it fits the existing output limit. All
original text and candidates remain. Yes, abstain and no bands preserve original
order within each band. The advice does not choose permissions, apply changes,
approve tests, add agents, select a Codex model or authorize commit/push. Untrusted
source instructions or confidently incorrect judgments can still mislead a model;
source inspection and normal verification remain necessary.

## What is actually evaluated

After activation, local counters automatically record attempted calls, failures,
cache hits, call latency and provider-reported input/output tokens from valid
responses. Failed or interrupted calls can also be billed without returning usage.
These counters measure added overhead, not saved Codex tokens or improved quality.

Review a query's original numbered hits against the source, then supply the
relevant IDs. Feedback is optional and must reflect external review, not Jev's
own answer being treated as ground truth:

```bash
harness-codex jev feedback --project /path/to/project --query-id QUERY_ID --relevant c2,c4
# Or --relevant none when no returned candidate was useful.
harness-codex jev status --project /path/to/project --json
```

Status compares baseline and suggested mean reciprocal rank: the average inverse
rank of the first relevant result, zero if none is relevant. Feedback replaces
an earlier label for the same query; retained labeled queries are counted once.
These are results on a small, user-selected, bounded cache, not an unbiased task
benchmark. Expiration/replacement, eviction, model changes and clearing can remove
labels. The report therefore retains `benefit: not-measured` for overall task
benefit and `automaticImprovement: false` even when ranking improves.

Harness, Graft and Jev do not jointly evaluate every conversation and rewrite
themselves in real time. [Existing maintenance](maintenance.md) allows separately
enabled, bounded corrections to existing project skills. It does not establish
causal performance benefit or automatically tune Jev/Graft. [Task evaluation](evaluation.md)
requires controlled comparisons. Compare ordinary search, Graft alone and
Graft plus Jev on equivalent tasks, keeping the Harness/model setup fixed; compare
Harness itself separately. Include failures, source correctness, total wall time,
all model usage, indexing and review costs. The shadow phase necessarily adds
observation cost and cannot demonstrate production savings by itself.
The existing paired evaluator does not automatically configure isolated Graft/Jev
arms or combine TypeSafe usage with Codex usage; those setup and accounting steps
must be explicit in the comparison.

## Local state and controls

State stays under the selected user's Graft storage, separate from project
artifacts, manifests and transactions. It contains keyed query fingerprints,
bounded probabilities, optional candidate-index labels and counters; no raw
questions, snippets, source paths, provider replies or API keys are persisted.
Existing caches survive tool uninstall, matching Graft's documented behavior.

```bash
harness-codex jev disable --project /path/to/project
harness-codex jev clear --project /path/to/project --yes
```

Disable preserves observations. Clear disables Jev and removes cached advice,
labels and aggregate counters, preserving the current daily call reservation so
clearing cannot bypass its budget. An interrupted parent may leave a local lock;
after ensuring no Jev command is running, remove only that owned Jev lock to retry.

The reviewed default is the versioned `jev-1.13.0`; `--model jev-X.Y.Z` permits
explicit version changes with cache invalidation and strict response-shape/model
checks. Availability and behavior still require provider validation.

References: [TypeSafe API](https://docs.typesafe.ai/api),
[Noul probabilities](https://docs.typesafe.ai/primitives/noul),
[versioned models](https://docs.typesafe.ai/models).
