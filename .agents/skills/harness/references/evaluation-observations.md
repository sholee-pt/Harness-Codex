# Evaluation Observations

Completed Run Schema 2 records are immutable. Facts learned later are stored as create-only Observation Schema 1 records and combined only in a computed Derived Evaluation View.

## Structured report

A user-owned report contains no free text and uses logical IDs from the configuration snapshot captured with the run:

```json
{
  "schemaVersion": 1,
  "captureMode": "agent-reported",
  "observedExecution": {
    "executionClass": "delegated",
    "routeRef": null,
    "agentRefs": ["contract_reviewer"],
    "skillRefs": [],
    "independentReview": true,
    "completeness": "partial"
  },
  "measurements": {},
  "verification": []
}
```

Ingest validates each component against the run-time declared reference set. It does not consult the current manifest as a fallback. The stored observation contains only repository-scoped HMAC pseudonyms and never copies the report or raw component names.

## Lifecycle

- `supplement` starts an independent active chain and requires a payload.
- `replacement` targets one active observation in the same repository and run, makes it inactive, and requires a payload.
- `withdrawal` targets one active observation, carries no payload, and terminates that chain.
- Re-adding withdrawn information requires a new supplement.

All lifecycle checks and the create-only write occur under the repository lock. Branches, missing targets, cross-run targets, cycles, and attempts to replace a withdrawal are conflicts. Inactive records remain inspectable and exportable.

Annotation Schema 2 applies the same immutable-successor principle to the user's acceptance and correction count, but permits only one active chain per run. Exactly one legacy Schema 1 annotation may act as its root; two or more legacy annotations are an unresolved conflict.

## Derived view

`harness_eval.py view --run RUN_ID` combines the Run record, active observations, and active annotation without persisting the result. Field-specific authority is used: runtime token usage cannot be overwritten by a report, verification-runner evidence outranks reported verification, and user acceptance comes only from the active user annotation. Equal-authority disagreements remain active conflicts.

Declared configuration and observed execution may differ normally. Expected and observed execution differences are protocol deviations. Two observations describing the same fact differently are observation conflicts.
