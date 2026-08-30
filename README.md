<p align="center">
  <img src="https://img.shields.io/badge/Version-2.1.0-brightgreen.svg" alt="Version">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Claude_Code-Plugin-purple.svg" alt="Claude Code Plugin">
  <img src="https://img.shields.io/badge/Execution_Modes-3-teal.svg" alt="3 Execution Modes">
  <img src="https://img.shields.io/badge/Patterns-6+Quality-orange.svg" alt="Patterns">
</p>

# Harness v2 — The Team-Architecture Factory for Claude Code

**English** | [한국어](README_KO.md)

> **Harness is a team-architecture factory for Claude Code.** One sentence — **"build a harness for this project"** · **"하네스 구성해줘"** — and the plugin turns your domain description into an agent team and the skills they use.

> **Reviewed derivative:** this `v2` branch uses the content of upstream PR [#56](https://github.com/revfactory/harness/pull/56) at `40530d4` as its review baseline, corrects runtime claims against current primary documentation, and records selective PR decisions in [`docs/upstream-pr-review.md`](docs/upstream-pr-review.md). The SHA identifies the reviewed content and does not imply that every distribution preserves upstream commit ancestry. Codex users should use the repository skill at [`.agents/skills/harness/SKILL.md`](.agents/skills/harness/SKILL.md).

## What's new in v2

v2 is a ground-up rebuild for the current Claude Code multi-agent runtime:

- **Three execution modes.** v2 separates deterministic workflows, experimental Agent Teams, and a one-shot-by-default Harness policy for subagents instead of treating them as one interchangeable API:
  1. **Workflow orchestration** — deterministic scripts (`pipeline()` / `parallel()` / schemas / explicit limits) for fan-outs, verification loops, and large-scale runs
  2. **Persistent agent collaboration** — Claude Code Agent Teams, with context retained across turns; experimental opt-in is required
  3. **Sub-agent delegation** — lightweight parallel dispatch, operated as one-shot by Harness unless steering or resume is explicitly needed
- **Workflow-native quality patterns.** Adversarial verification, judge panels, loop-until-dry, multi-modal sweeps, completeness critics — codified so generated harnesses filter out plausible-but-wrong output.
- **Explicit feature boundaries.** Workflow and ordinary subagent modes do not require Agent Teams. Persistent teammate collaboration still requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.
- **Runtime-aware model policy.** v1 pinned every agent to `model: "opus"`. v2 inherits the current runtime default unless a role has a documented reason for an override, and verifies that the selected model is actually available.
- **`/harness:evolve` actually ships.** The evolution mechanism v1 only documented is now a real skill: it captures the delta between your initial and current harness, generalizes feedback, and feeds it back into agents/skills/orchestrators.
- **v1 migration built in.** The factory detects hard-coded legacy team-tool call patterns and offers a migration path while preserving the current Agent Teams opt-in requirement.

## Core features

- **Agent team design** — six architecture patterns (Pipeline, Fan-out/Fan-in, Expert Pool, Producer-Reviewer, Supervisor, Hierarchical Delegation), each mapped to its best v2 execution mode
- **Skill generation** — context-efficient skills via Progressive Disclosure, with reuse checks before generating duplicate agents or skills
- **Orchestration** — data-passing protocols (structured schemas, files, messages, tasks), error handling, resume support
- **Verification** — trigger evals, dry runs, with-skill vs. without-skill A/B testing (optionally as a workflow itself)
- **Evolution** — `/harness:evolve` turns usage feedback into measurable next-generation improvements

## Category — Where Harness Sits

Harness lives at the **L3 Meta-Factory** layer of the Claude Code ecosystem — the layer that generates other harnesses rather than being one. Inside L3, it occupies the **Team-Architecture Factory** sub-layer.

| Layer | What it does | Neighbors we coexist with |
|-------|--------------|---------------------------|
| **L3 — Meta-Factory / Team-Architecture Factory** (us) | Domain sentence → agent team + skills, via six pre-defined team patterns | — |
| L3 — Meta-Factory / Runtime-Configuration Factory | Deterministic, repeatable runtime configurations | [coleam00/Archon](https://github.com/coleam00/Archon) |
| L3 — Meta-Factory / Codex Runtime Port | Same concept, Codex runtime | [SaehwanPark/meta-harness](https://github.com/SaehwanPark/meta-harness) |
| L2 — Cross-Harness Workflow | Standardize skills/rules/hooks across multiple harnesses | [affaan-m/ECC](https://github.com/affaan-m/everything-claude-code) |

> Archon generates deterministic runtime configurations. Harness generates team architectures plus the skills agents use. Pick Archon for runtime determinism, Harness for team architecture, or combine them.

## Codex usage

Open the repository in Codex and ask `Build a Codex harness for this project` or invoke `$harness` explicitly. The repo-scoped skill generates reusable workflows under `.agents/skills/`, independently runnable specialists under `.codex/agents/` when useful, concise `AGENTS.md` routing, and `_workspace/` handoffs.

The Codex port selectively adapts the useful core of draft PR [#49](https://github.com/revfactory/harness/pull/49). It does not include that PR's stale v1 copy, generated workspace artifacts, or repo marketplace packaging.

## Workflow

```
Phase 0: Audit existing harness (new / extend / maintain — v1 artifacts detected here)
Phase 1: Domain analysis (incl. control-flow shape of the work)
Phase 2: Execution mode & team architecture design
Phase 3: Agent definitions (.claude/agents/)
Phase 4: Skill generation (.claude/skills/)
Phase 5: Orchestration & CLAUDE.md pointer
Phase 6: Verification & testing
Phase 7: Maintenance — evolution via /harness:evolve
```

## Install

### Via marketplace

```shell
/plugin marketplace add sholee-pt/harness-codex-v2@v2
/plugin install harness@harness-marketplace
```

Because this derivative is private, the current GitHub credentials must have read access to `sholee-pt/harness-codex-v2`.

### As global skills

```shell
cp -r skills/harness ~/.claude/skills/harness
cp -r skills/evolve ~/.claude/skills/harness-evolve
```

No environment variable is required for Workflow or ordinary subagent modes. Agent Teams mode requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.

## Usage

```
하네스 구성해줘
build a harness for this project
design an agent team for <domain>
```

After using a generated harness:

```
하네스 회고해줘 / evolve the harness with this feedback
```

### Choosing an execution mode

| Mode | Primitive | When |
|------|-----------|------|
| **Workflow orchestration** | `Workflow` scripts | Control flow is deterministic: enumerable fan-outs, verification loops, large scale, structured outputs |
| **Persistent agents** | Agent Teams (experimental opt-in) | Long-lived specialists that keep context; iterative feedback and negotiation |
| **Sub-agent delegation** | `Agent` calls (one-shot Harness policy) | Independent parallel work where one returned result per call is sufficient; current runtimes can still support steering and resume when explicitly used |

The factory picks the mode from the **shape of the control flow**, not from team size — and mixes modes per phase when that fits better.

## Generated artifacts

```
your-project/
├── .claude/
│   ├── agents/          # agent definitions (who)
│   │   ├── analyst.md
│   │   ├── builder.md
│   │   └── qa.md
│   └── skills/          # skills (how) + one orchestrator (who-when-in-what-order)
│       ├── analyze/SKILL.md
│       └── build/SKILL.md
└── CLAUDE.md            # minimal pointer: trigger rule + change history
```

## Migrating from v1

See [docs/migration-v1-to-v2.md](docs/migration-v1-to-v2.md). Summary: replace hard-coded team-tool call schemas with natural-language team intent, keep the experimental flag when Agent Teams is selected, convert deterministic fan-outs to Workflow scripts, and avoid stale blanket model pins.

## Prior results (v1)

A controlled A/B on 15 software-engineering tasks measured the effect of structured pre-configuration on LLM code-agent output quality: mean quality 49.5 → 79.3 (+60%), 15/15 win rate, −32% output variance (n=15, author-run, see [revfactory/claude-code-harness](https://github.com/revfactory/claude-code-harness)). Treat these as author-measured numbers; run your own pilot for adoption decisions.

## License

Apache 2.0
