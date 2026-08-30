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
2. If the manifest uses schema v1, run the guarded migration command only while every managed entry is unchanged.
3. Recompute the project profile and topology from current evidence.
4. Put the proposed content in a structured plan and run `harness_apply.py --dry-run`.
5. Apply only when every existing managed entry is unchanged and every new target path is unused.
6. Let the apply script replace or append exactly one managed pointer block in the instruction file Codex will actually load.
7. Let the apply script derive and atomically write the new manifest after planned files are stable.
8. Run status again; a second identical plan must produce no diff.

Do not automatically delete obsolete managed files. List them as removal candidates and require explicit authorization. Never use a recursive delete against a repository root.

The legacy `record` command is initialization-only and refuses to replace an existing managed baseline. If the manifest is malformed or belongs to another runtime, stop automatic updates and report the discrepancy.
