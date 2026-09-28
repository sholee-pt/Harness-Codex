# Capture Provenance

Every quantitative value uses a measurement object with `value`, `unit`, `state`, `source`, `fidelity`, and `completeness`.

## Required distinctions

- `0` means the observed value was zero.
- `null` with `unavailable` means it was not measured.
- A corrupt record is invalid and must not be represented as unavailable data.
- Agent and user reports use `reported`, never `exact`.
- Token values are copied only from terminal JSONL usage. They are never estimated or recombined into an invented total.

`streamCompleteness` describes the JSONL stream. Each measurement's `completeness` describes metric coverage. A terminal event does not make a metric complete when unknown or malformed events may affect it.

Records include `parserVersion` and `parserCompatibility`. Unknown payloads are counted and discarded. They downgrade parser compatibility and metric completeness without retaining message, command, path, reasoning, or source content.

Task classification and execution configuration have their own provenance. Configured or assigned agents are not described as runtime-observed agents unless the event stream explicitly proves invocation.

## Usage coverage in `view`

`harness_eval.py view --run RUN_ID` adds a non-persistent `usageSummary` at the presentation boundary. It separates selected terminal-event measurements, reported-only values, unavailable counters, and conflicts. It preserves each measurement's fidelity and completeness; zero remains measured zero. A conflicted counter has no selected value.

Terminal-event scope does not establish parent-only or all-child coverage. Child coverage and counter overlap remain unverified, account usage is not measured, and no total token or billing-cost value is computed. Cached-input and reasoning-output counters must not be added blindly to input/output counters. Generation, operations, evaluation, and unrelated runs are not a measured lifecycle total. The summary is not persisted and does not alter immutable records, Derived View fingerprints, or attribution eligibility.

Comparison plans may separately select `input-tokens`, `cached-input-tokens`, `output-tokens`, or `reasoning-output-tokens`. These are reported counters, not account costs. Choose direction explicitly: more cache hits can be beneficial depending on the experiment. If either counter is missing or has incomplete metric coverage, both paired outcome values and the delta remain unavailable with unknown direction; each arm's original values remain inspectable in its view. Partial numbers cannot become complete evidence merely because both arms contain a number. Keep the same runtime stratum, coverage limitations, and correctness gate when comparing arms.

Reasoning-effort labels are bounded identifiers obtained from the selected runtime/model, not a fixed Harness list. `unknown` records missing provenance and sends no override. Native Codex validates execution support; a rejected combination is a failed capture, never retried with different inference or permissions.
