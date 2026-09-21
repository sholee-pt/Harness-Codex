# v0.16.0-beta dependency and optimization review

This review covers the generation/application chain and its runtime consumers.
It is not a claim that all possible bottlenecks have been eliminated. The change
keeps Plan Schema 3, Manifest Schema 7 and Transaction Schema 2, generated
ownership semantics, rollback, supported upgrades and existing validity gates.

| Path | Finding | Resolution |
| --- | --- | --- |
| Draft builder -> Plan -> apply | Project and topology claims repeatedly hash and decode the same source. | Share a bounded evidence snapshot during one plan-validation pass. |
| Manifest -> installed validator/doctor | The same repeated source work occurs; source drift also marked artifact compatibility failed. | Reuse evidence work; derive compatibility from the contract itself. Add `managedIntegrityValid`. |
| CLI -> missing-reference classification | Each missing claim reparsed the full manifest. | Read once per classification; retain per-reference metadata and lexical-path checks. |
| Plan -> Transaction staging -> commit | Several hashes occur at distinct points while files can change. | Keep fresh checks; these are mutation preconditions, not redundant advisory reads. |
| Transaction -> interrupted recovery | Backup/staging fingerprints protect recovery data independently of live files. | Keep validation, manifest-last order and rollback gates unchanged. |
| Runtime plan -> coordination -> relay/receipt | Bindings tie messages and review lineage to a specific plan/manifest. | Keep boundaries and end-of-validation manifest reread; no cross-call cache. |
| Task checkpoints -> dependent tasks | A per-scan file cache already exists; changed inputs invalidate dependents. | Preserve selective invalidation and active-writer ownership; no global regeneration. |
| Maintenance/evaluation | Their digests bind different serialization/provenance contracts. | Do not merge superficially similar helpers or change historical fingerprints. |
| Retrieval -> native work | Upstream CLI can perform unrelated upkeep/global wiring; graph estimates are not observed savings. | Use opt-in structural library calls with bounded query output and ordinary-search fallback. |

Evidence snapshots retain at most 16 MiB of source bytes in one pass. Hash and
line-count work is reused while metadata is stable. Before returning, cached
files are read again and compared byte-for-byte, including same-size changes
with restored timestamps. Larger or over-budget files use uncached reads;
they are not rejected. The cache is never reused across commands, transaction
stages, applies or recovery. It is not a substitute for filesystem isolation
against concurrent hostile writers.

`valid`, `installationStatus`, the legacy aggregate `integrityValid`, and exit
codes retain their previous strict semantics. `managedIntegrityValid` describes
managed-file/ownership checks; `artifactCompatibility` describes the versioned
contract. Neither alone authorizes apply. Source freshness remains separate,
and existing reviewed stale-evidence handling remains in the CLI. Malformed
contracts and modified managed files are not silently relabelled valid.

Cross-validation uses the immediately preceding v0.15.0-beta source. Existing
transaction/upgrade/runtime-plan tests remain part of regression coverage;
there is no full historical source comparison matrix. Graft's actual Linux
package smoke is a release gate separate from adapter unit tests. No offline
test establishes live-agent quality or token-cost improvement.
