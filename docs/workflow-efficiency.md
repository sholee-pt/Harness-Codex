# Workflow efficiency and integration scope

Harness v0.21.0-beta selectively applies concepts reviewed in
[oh-my-codex](https://github.com/Yeachan-Heo/oh-my-codex/tree/cdc24a71408ebd6bd0362f52170f0d7998f77007)
(package 0.21.6). The implementation is independently authored; OMX source,
prompts and runtime are not bundled or installed as dependencies.

| Reviewed concept | Harness behavior |
| --- | --- |
| [Ordinary-task routing](https://github.com/Yeachan-Heo/oh-my-codex/blob/cdc24a71408ebd6bd0362f52170f0d7998f77007/docs/ordinary-task-routing.md) | The project router receives concise guidance distinguishing actual requests from quoted workflow names. Small tasks keep direct execution; scope growth does not require extra agents. |
| [Prompt inventory](https://github.com/Yeachan-Heo/oh-my-codex/blob/cdc24a71408ebd6bd0362f52170f0d7998f77007/src/scripts/prompt-inventory.ts) | Materialization and doctor report static bytes/characters, discovery-description size and repeated prose. No scan runs per conversation turn, and no model is called. |
| [Task claims](https://github.com/Yeachan-Heo/oh-my-codex/blob/cdc24a71408ebd6bd0362f52170f0d7998f77007/src/team/state/tasks.ts) and [reassignment](https://github.com/Yeachan-Heo/oh-my-codex/blob/cdc24a71408ebd6bd0362f52170f0d7998f77007/src/team/rebalance-policy.ts) | Project mutations are serialized and fenced by transaction identity. Runtime guidance permits only ready work and observed available workers; native Codex still owns execution. |
| [Bounded verification](https://github.com/Yeachan-Heo/oh-my-codex/blob/cdc24a71408ebd6bd0362f52170f0d7998f77007/skills/ultraqa/SKILL.md) | Verification scenarios follow the changed behavior. Existing retry budgets remain; a repeated failure without new evidence stops the loop. Actual check results remain necessary for checkpoint completion. |

These additions do not install OMX's tmux/team runtime, global configuration,
prompts, keyword hooks or model selection. Harness retains one project router,
native Codex sessions and permissions, optional Graft navigation and bounded Jev
advice. No tool can declare task success from a verifier's prose alone.

## Inspect instruction overhead

```sh
harness-codex doctor --project /path/to/project
harness-codex doctor --project /path/to/project --json
```

`instructionInventory` covers root instruction candidates, the installed generator
entrypoint and manifest-listed skills/agents. It does not scan unrelated source,
global/user instructions or plugins. Root instruction candidates may be mutually
exclusive; on-demand skills and agent instructions need not be loaded together.
Discovery-description characters are reported separately. Required canonical
contract blocks are excluded from duplicate-prose suggestions, but included in
file-size totals. Oversized or unreadable entries appear under `skipped`; that
inventory limitation neither changes ownership validation nor blocks ordinary work.

The inventory stores no report or raw paragraphs and performs no deletion.
Review context before removing repetition. Static size is not measured token use,
cache behavior, latency, task quality or cost reduction.

New router materialization uses a compact canonical teamplay block. Detailed task
plans, packets, relay receipts and observation procedures are loaded only when
the relevant delegation path is selected. Existing canonical v2 installations
remain valid without being rewritten; a reviewed `config` can adopt the compact
block. The first real subagent's acknowledged handle is a dispatch-readiness
check, so independent agents can start before that first task completes.

Delegated tasks use five-minute progress checkpoints and a thirty-minute total
budget. Extensions require new observed progress; a repeated running status does
not renew a deadline. Poll counts are measurements, not failure conditions.
Receipt policy overruns remain separate warnings and preserve an observed
terminal outcome. These checks remain instruction-driven; receipts do not act
as a scheduler or prove that a deadline was enforced.

## Existing projects and state

Update the tool with `harness-codex update`. Existing supported project contracts
remain usable. Use `harness-codex config --project /path/to/project` when you want a
reviewed update to generated instructions; no reset is required. Already installed
project-local helper copies keep their existing code until that configuration
refresh. Tool-only updates do not silently rewrite project files.

Project mutations use OS advisory locks in a user-specific directory in the OS
temporary directory (override with `HARNESS_LOCK_HOME`). This does not require
permission to write the user's home from a project sandbox. Lock files may remain, but process exit releases their
locks automatically. Do not delete a lock file while another Harness command is
active. Apply, recovery and removal for the same project must use the same lock
home and OS temporary directory on the same host. This is not a distributed lock
between different machines. Transaction ownership/hashes remain checked independently of that lock.

Graft setup commits only while its starting preference is still current. A newer
disable or enable wins over an earlier slow build. Jev's OS lock releases after a
crash; reserved daily call counts remain, since an interrupted request might have
reached the provider. Dead legacy PID locks can be recovered; live or ambiguous
legacy locks remain protected.

Checkpoint status requires the entire stored task set for `complete: true`. A
partial plan reports `planMatchesRun: false`; use `resume` with a new run for a
deliberate replacement plan. Linux verification timeouts kill the verifier's
process group. This does not establish that native agents stopped: their observed
lifecycle remains a separate requirement.

Deterministic regressions and upgrade tests verify these boundaries. They do not
establish better fresh generation, live native delegation, model accuracy or token
savings; those require separate real-task comparisons.
