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

Supported Codex reasoning-effort labels are `minimal`, `low`, `medium`, `high`, `xhigh`, and `unknown`. Model support is checked separately; `xhigh` is not universal.
