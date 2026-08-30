# Safe Update Protocol

Read this reference before modifying a repository that already contains harness or instruction artifacts.

## Ownership classes

- **Managed and unchanged:** listed in the manifest and current hash matches; may be updated.
- **Managed and modified:** listed but hash differs; preserve and report a conflict.
- **User-owned:** not listed in the manifest; never overwrite it.
- **Managed pointer block:** only text between `<!-- harness:begin -->` and `<!-- harness:end -->` is owned by Harness.

An existing dedicated target path without a valid matching manifest entry is user-owned, even if its name resembles a generated artifact.

## Update sequence

1. Run the state status command before writing.
2. If status reports a transaction journal, read [transaction-recovery.md](transaction-recovery.md) and run `harness_apply.py --recover` before migration or planning. Recovery refuses targets whose content changed outside the interrupted transaction.
3. If the manifest uses schema v1 or v2, run the guarded migration command only while every managed entry is unchanged.
4. Recompute the project profile and topology from current evidence.
5. Put the proposed content in a structured plan and run `harness_apply.py --dry-run`.
6. Apply only when every existing managed entry is unchanged and every new target path is unused.
7. Let the apply script stage desired content and verified backups, write the transaction journal, and replace exactly the outputs classified as create or update.
8. Let the apply script write the derived manifest last and remove the journal only after every output is committed.
9. Run status again; a second identical plan must perform no file write.

Do not automatically delete obsolete managed files. List them as removal candidates and require explicit authorization. Never use a recursive delete against a repository root.

The legacy `record` command is initialization-only and refuses to replace an existing managed baseline. If the manifest, journal, or backup is malformed or belongs to another runtime, stop automatic updates and report the discrepancy. Do not manually delete a recovery journal unless every target and backup has been inspected.
