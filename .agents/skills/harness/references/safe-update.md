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
2. Recompute the project profile and topology from current evidence.
3. Update only managed and unchanged files.
4. Add new files only at unused paths.
5. Replace or append exactly one managed pointer block while preserving all surrounding root instructions.
6. Record new hashes only after final content is stable.
7. Run status again; a second identical generation must produce no diff.

Do not automatically delete obsolete managed files. List them as removal candidates and require explicit authorization. Never use a recursive delete against a repository root.

If the manifest is malformed or belongs to another runtime, stop automatic updates and report the discrepancy.
