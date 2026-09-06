# Evaluation Schemas

The normative validators are in `scripts/harness_eval_types.py`. All schemas reject unknown fields where the validator defines a closed object.

## Run Record Schema 2

A record contains:

- capture mode, stream completeness, parser version, and compatibility;
- timestamps and pseudonymous repository identity;
- Codex version, surface, model reference, reasoning effort, platform, and sandbox;
- task category and classification source;
- declared configuration, expected execution, discovered configuration, and observed execution;
- metric-level provenance;
- verification results and critical failure status;
- paired-comparison isolation state;
- explicit privacy flags and content fingerprints; and
- a canonical SHA-256 integrity digest.

Pending records have `endedAt: null`. Completed records are immutable and require a timestamp. Later facts use separate Observation Schema 1 records; user outcomes use an Annotation Schema 2 active chain.

`resultFingerprint` covers the tracked diff from the evaluator's task base plus every non-ignored untracked regular file or symlink. For `paired-run`, the task base is a clean synthetic commit created after arm preparation; both arms still record the original user commit as `sourceSnapshotId`. Capture is bounded and all-or-nothing: incomplete capture stores an unavailable value, never a digest of a partial result, without lowering environment isolation. Annotation correction count may be unavailable; measured values are non-negative integers, and `accepted-with-corrections` requires a measured value of at least one.

Comparison Schema 2 records the declared configuration delta, protocol deviations, a plan- and Harness-version-bound task/runtime stratum fingerprint, the exact Derived View fingerprints used, and result-fingerprint completeness. An asymmetric unknown configuration produces an unavailable delta and cannot support attribution. Proposal Schema 2 can repeat only an eligible measured delta from complete, independent Run pairs bound to the validated plan. Both records are closed, integrity-checked, non-causal, and never auto-applicable.

## Comparison Plan Schema 2

The `paired-run` command requires and validates the comparison plan before either arm runs. A standalone `compare` result is bound to a plan digest but is not proof that the plan existed before its Runs. Harness does not currently provide durable or tamper-evident preregistration. The plan declares:

```json
{
  "schemaVersion": 2,
  "primaryOutcome": {
    "metric": "verification-pass-rate",
    "direction": "higher-is-better",
    "minimumEffect": 0.05
  },
  "correctnessGate": "no-regression",
  "secondaryOutcomes": ["wall-time-ms", "output-tokens"],
  "verificationProfileFingerprint": null,
  "intervention": {
    "expectedChangedFactors": ["change-discipline-version"],
    "attributionTarget": "single-factor"
  },
  "taskStratum": {
    "category": "bugfix",
    "complexityLevel": "low",
    "impactLevel": "medium",
    "uncertaintyLevel": "low",
    "scopeClass": "single-file"
  },
  "patchScopeProfileFingerprint": null
}
```

For `paired-run`, the primary outcome is supplied before arm execution. Standalone plan binding alone cannot prove this timing. Cost improvements cannot override a correctness regression.

v9.1 also accepts `input-tokens`, `cached-input-tokens`, and `reasoning-output-tokens` alongside `output-tokens`. Each selects one existing measurement and never constructs a sum. A counter's direction must be selected for the experiment; cached input is not inherently a lower-is-better metric. Existing plans remain valid. Missing counters remain unavailable and existing completeness and correctness gates still apply.

The CLI `view` adds a presentation-only `usageSummary`; it is not part of Run, Observation, Comparison, or Derived View fingerprint schemas. It does not expand the capture's known usage scope or authorize configuration attribution.

`single-factor` requires exactly one expected changed factor, while `bundle` requires at least two. `descriptive-only` can never authorize a concrete candidate. The proposal command keeps `--comparison-plan` optional for compatibility, but omitting it disables concrete positive and negative attribution.

## Observation and annotation lifecycle

Observation records are immutable supplements, replacements, or withdrawals. Replacements and withdrawals must target the current active observation in the same repository and run. Withdrawal is terminal for that chain and carries no payload. Raw logical component IDs are accepted only in a user-owned report, validated against the Run snapshot, pseudonymized, and never retained.

Annotation Schema 2 permits one active chain per run. A replacement names the active annotation. Zero legacy Schema 1 annotations means no active value, one may serve as a legacy root, and two or more are an unresolved conflict rather than an invitation to guess by time or filename.

The Derived Evaluation View combines a completed run with active observations and the active annotation. It applies field-specific authority, reports equal-authority conflicts and expected-versus-observed protocol deviations, and is computed rather than persisted. Comparisons bind to a digest of each arm's view so a later replacement, withdrawal, or annotation does not retroactively alter old evidence.

## Canonical form

- UTF-8 and LF;
- lexically sorted object keys;
- two-space indentation and one trailing newline;
- UTC RFC3339 timestamps ending in `Z`;
- finite numbers only; and
- an integrity hash calculated with `integrity.recordSha256` set to `null`.

The digest detects accidental corruption. It is not a signature.
