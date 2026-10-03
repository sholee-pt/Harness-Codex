# Safe Update Protocol

Read this reference before modifying a repository that already contains harness or instruction artifacts.

## Ownership classes

- **Managed and unchanged:** listed in the manifest and current hash matches; may be updated.
- **Managed and modified:** listed but hash differs; preserve and report a conflict.
- **User-owned:** not listed in the manifest; never overwrite it.
- **Managed pointer block:** only text between `<!-- harness:begin -->` and `<!-- harness:end -->` is owned by Harness.
- **Root instruction evidence:** `instruction-user-content` hash는 위 pointer를 제외한 사용자 원문에 적용할 것. Pointer 갱신은 근거 변경으로 취급하지 않으며, 사용자 본문 변경은 현재 source를 다시 검토할 것. 사용자 지정 fallback instruction에도 같은 소유권·복구 계약을 적용할 것.
- **Tracked target:** Git tracking is independent of Harness ownership. A clean managed file may be updated, while a user-owned file stays protected regardless of tracking.
- **Legacy exclusion block:** an earlier Harness marker in Git metadata remains outside v9.5 ownership and is preserved without blocking generation.

An existing dedicated target path without a valid matching manifest entry is user-owned, even if its name resembles a generated artifact.

## Update sequence

1. Run the state status command before writing.
2. If status reports a transaction journal, read [transaction-recovery.md](transaction-recovery.md) and run `harness_apply.py --recover` before migration or planning. Recovery refuses targets whose content changed outside the interrupted transaction.
3. If the manifest uses schema v1, v2, or v3, run the guarded migration command only while every managed entry is unchanged; this prepares schema 4 and does not invent schema 5 boundaries.
4. For Schema 4, 5, 6, or 7, recompute topology from current evidence. Schema 4/5 regeneration and recognized Schema 6 workspace-contract upgrades produce Schema 7 through a reviewed plan.
   For Schema 6/7, apply independently checks generator, schema, workspace scope, and artifact compatibility before writes. Recognized v7 installations without a marker and v8.0/v8.1 Artifact Contract 1 installations may upgrade only after legacy integrity and required v8 agent-contract checks pass. Unsupported or incomplete combinations remain errors; see [generated-contracts.md](generated-contracts.md).
5. Put the proposed content in a schema 3 plan and run `harness_apply.py --dry-run`.
6. Apply only when managed entries are unchanged and new target paths are unused. Git-root alignment, nested repositories, registered worktree count, and tracking do not replace ownership checks.
7. Let the apply script stage desired content and verified backups, write the transaction journal, and replace exactly the outputs classified as create or update.
8. Review `removalCandidates`; omitted owned files are retained until explicit removal. Subsequent validator/doctor reports `pendingRetirement` for retained native entry points outside topology. Do not infer that removal from topology disables native discovery.
9. Let the apply script write the derived manifest last and remove the journal only after every output is committed.
10. Run status again; a second identical plan must perform no file write.

Do not automatically delete obsolete managed files. List them as removal candidates and require explicit authorization. Never use a recursive delete against a repository root.

Project apply keeps its journaled recovery contract. No Git exclusion write or compensating Git restoration occurs in v9.5; existing exclusion content remains unchanged even when project apply fails.

The legacy `record` command is initialization-only and refuses to replace an existing managed baseline. If the manifest, journal, or backup is malformed or belongs to another runtime, stop automatic updates and report the discrepancy. Do not manually delete a recovery journal unless every target and backup has been inspected.
