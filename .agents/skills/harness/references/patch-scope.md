# Patch-Scope Evaluation

Patch-scope evaluation checks whether Git-visible changed paths stay inside a user-owned scope profile. It does not prove that the content is semantically minimal.

```json
{
  "schemaVersion": 1,
  "id": "single-parser-fix",
  "allowedScopes": ["src/parser.py", "tests/test_parser.py"],
  "allowUntracked": false,
  "maximumChangedPaths": 2,
  "maximumAddedLines": null,
  "maximumDeletedLines": null
}
```

Literal scopes authorize only one path. A scope ending in `/**` authorizes that directory recursively. Traversal and absolute paths are rejected.

The evaluator reads tracked changes from `HEAD` and non-ignored untracked paths, counts both sides of a rename or copy, applies path and line budgets, and stores only the profile digest, counts, booleans, and repository-scoped path pseudonyms. Raw paths and profile content remain outside evaluation state.

Pass `--patch-scope-profile PROFILE.json` to `run` or `paired-run`. A paired Comparison Plan Schema 2 must predeclare the same profile fingerprint; a mismatched measured profile rejects comparison. A matching but partial or unavailable measurement may be retained descriptively. Concrete attribution requires complete matching measurements from both arms, no changed-path limit violation, and both arms within the declared scope. A baseline violation is recorded as `baseline-patch-scope-violation`; any violation or incomplete arm blocks all factor, bundle, and candidate-bearing negative proposals.
