# Evaluation Schemas

The normative validators are in `scripts/harness_eval_types.py`. All schemas reject unknown fields where the validator defines a closed object.

## Run Record Schema 1

A record contains:

- capture mode, stream completeness, parser version, and compatibility;
- timestamps and pseudonymous repository identity;
- Codex version, surface, model reference, reasoning effort, platform, and sandbox;
- task category and classification source;
- configured execution and separately observed execution;
- metric-level provenance;
- verification results and critical failure status;
- paired-comparison isolation state;
- explicit privacy flags and content fingerprints; and
- a canonical SHA-256 integrity digest.

Pending records have `endedAt: null`. Completed records are immutable and require a timestamp. Acceptance and corrections use separate Annotation Schema 1 records.

`resultFingerprint` covers the tracked diff from `HEAD` plus every non-ignored untracked regular file or symlink. Capture is bounded and all-or-nothing: incomplete capture stores `null`, never a digest of a partial result. Annotation correction count may be unavailable; measured values are non-negative integers, and `accepted-with-corrections` requires a measured value of at least one.

Comparison Schema 1 and Proposal Schema 1 are closed, integrity-checked objects. Comparison records cannot claim causality, and proposal records cannot set `autoApplicable` to true.

## Comparison Plan Schema 1

The comparison plan is fixed before either arm runs. It declares:

```json
{
  "schemaVersion": 1,
  "primaryOutcome": {
    "metric": "verification-pass-rate",
    "direction": "higher-is-better",
    "minimumEffect": 0.05
  },
  "correctnessGate": "no-regression",
  "secondaryOutcomes": ["wall-time-ms", "output-tokens"],
  "verificationProfileFingerprint": null
}
```

The primary outcome cannot be chosen after observing results. Cost improvements cannot override a correctness regression.

## Canonical form

- UTF-8 and LF;
- lexically sorted object keys;
- two-space indentation and one trailing newline;
- UTC RFC3339 timestamps ending in `Z`;
- finite numbers only; and
- an integrity hash calculated with `integrity.recordSha256` set to `null`.

The digest detects accidental corruption. It is not a signature.
