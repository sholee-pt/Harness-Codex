# Safe Update Protocol

Read this reference before modifying a repository that already contains harness or instruction artifacts.

## Ownership classes

- **Managed and unchanged:** listed in the manifest and current hash matches; may be updated.
- **Managed and modified:** listed but hash differs; preserve and report a conflict.
- **User-owned:** not listed in the manifest; never overwrite it.
- **Managed pointer block:** only text between `<!-- harness:begin -->` and `<!-- harness:end -->` is owned by Harness.
- **Tracked target:** any path already present in the local Git index; v7 local-only mode refuses to modify it even when an older manifest recorded it.
- **Unbound local-protection block:** a Harness marker in the common Git `info/exclude` file without a matching manifest; preserve it as an explicit conflict rather than adopting it.

An existing dedicated target path without a valid matching manifest entry is user-owned, even if its name resembles a generated artifact.

## Update sequence

1. Run the state status command before writing.
2. If status reports a transaction journal, read [transaction-recovery.md](transaction-recovery.md) and run `harness_apply.py --recover` before migration or planning. Recovery refuses targets whose content changed outside the interrupted transaction.
3. If the manifest uses schema v1, v2, or v3, run the guarded migration command only while every managed entry is unchanged; this prepares schema 4 and does not invent schema 5 boundaries.
4. For schema 4, 5, or 6, recompute material boundaries, persistence, merge results, and project topology from current evidence. Treat schema 4/5 → 6 as a reviewed regeneration upgrade rather than an automatic schema inference.
   For Schema 6, normal apply independently rejects unsupported or incomplete generator/artifact contract combinations before any write. Supported v8.0/v8.1 Artifact Contract 1 installations and recognized unversioned v7 legacy installations may proceed through the normal ownership checks; see [generated-contracts.md](generated-contracts.md). A valid incoming plan is not permission to replace an unsupported existing contract. Recovery remains its separate journal-checked procedure.
5. Put the proposed content in a schema 3 plan and run `harness_apply.py --dry-run`.
6. Apply only when every existing managed entry is unchanged, every new target path is unused, and no intended target is Git-tracked. In a Git workspace, require exactly one registered worktree and verify the proposed literal-encoded local `info/exclude` action before applying.
7. Let the apply script stage desired content and verified backups, write the transaction journal, and replace exactly the outputs classified as create or update.
8. Let the apply script write the derived manifest last and remove the journal only after every output is committed.
9. Run status again; a second identical plan must perform no file write.

Do not automatically delete obsolete managed files. List them as removal candidates and require explicit authorization. Never use a recursive delete against a repository root.

If a synchronous failure happens after Harness changes `info/exclude` but before a pending transaction exists, compensating restoration is allowed only while the current exclusion content still equals Harness's destination content. Preserve external edits and any exclusion needed to hide a pending or recovery-required transaction. Abrupt termination before journal creation is a known limit of this maintenance contract, not a state that may be inferred as safely restored.

The legacy `record` command is initialization-only and refuses to replace an existing managed baseline. If the manifest, journal, or backup is malformed or belongs to another runtime, stop automatic updates and report the discrepancy. Do not manually delete a recovery journal unless every target and backup has been inspected.
