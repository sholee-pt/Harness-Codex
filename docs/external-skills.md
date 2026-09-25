# External skills and selected upstream concepts

Harness can reuse project-local specialist skills without making them generated Harness artifacts. The generator inventories installed skill metadata during configuration and reads only relevant procedures. It creates a small project-specific adapter only when that adds value. Ordinary turns do not rescan all skills or hash every bundle.

## Import a reviewed local skill

Acquire and review the upstream source separately. Select a single skill directory, including its references/scripts/assets, rather than an entire repository. For example, after checking out the desired K-Dense revision locally:

```bash
harness-codex skills add --project /path/to/project \
  --source /path/to/scientific-agent-skills/skills/scanpy --dry-run

harness-codex skills add --project /path/to/project \
  --source /path/to/scientific-agent-skills/skills/scanpy \
  --license-file /path/to/scientific-agent-skills/LICENSE

harness-codex skills list --project /path/to/project
harness-codex config --project /path/to/project
```

Use the license filename actually present in the checked-out repository. If its license and notices are already inside the skill, they are copied as part of the bundle. Optionally supply both `--upstream https://github.com/OWNER/REPO` and `--revision FULL_40_CHARACTER_COMMIT_SHA`. These fields record the provenance you declare; import does not query Git or certify the origin. No source scripts, setup hooks, dependency installers or model calls run during import.

The original skill name, metadata and resource bytes remain intact. A separate `.harness-external.json` inside the copied skill records imported file hashes and modes. Generated skills retain their stricter frontmatter contract. External metadata discovery supports unquoted top-level keys with single-line `name` and `description`; optional metadata is preserved but not fully YAML-validated. Unsupported headers are reported, not rewritten. Missing package dependencies, relative resources outside the copied bundle and live Codex discovery still need task-specific review.

Import refuses existing destinations, name collisions, links/reparse points, repository metadata, and overlapping source/destination trees. It stages the complete bundle before publishing it without replacing an existing directory. Import is bounded to 1024 files, 2048 entries and 64 MiB; these are bundle-import limits, not limits on the project's source files. It needs Linux `renameat2` support; Windows implementation remains retained source without a new Windows release.

```bash
harness-codex skills verify --project /path/to/project --name scanpy
```

Verification compares the selected external bundle with its local receipt and reports edits, additions and deletions. It does not establish upstream authenticity or skill quality, and is never a gate for starting Codex. External updates are reviewed separately; this version has no automatic external updater or remover. Harness `config`, `reset`, `remove`, tool update and uninstall preserve external skills. The generator and project manifest do not take ownership of them.

## What was adopted

The following reviewed snapshots inform independently authored integration and procedural guidance. None of these projects is bundled as a second agent runtime or automatically installed as a dependency. Existing upstream licenses remain applicable to skills users choose to import.

| Source snapshot | Selected benefit | Boundary retained |
| --- | --- | --- |
| [oh-my-codex `cdc24a7`](https://github.com/Yeachan-Heo/oh-my-codex/tree/cdc24a71408ebd6bd0362f52170f0d7998f77007) | Existing ordinary-task routing, bounded review, ownership and selective checkpoint reuse | No duplicate tmux/team runtime or keyword-triggered autonomous loop; see [existing integration](workflow-efficiency.md) |
| [Karpathy guidelines `2c60614`](https://github.com/multica-ai/andrej-karpathy-skills/tree/2c606141936f1eeef17fa3043a72095b4765b9c2) | Existing materialized assumptions, simplicity, scoped edits and verifiable goals | Reuse the canonical contract instead of repeating generic coding instructions in every skill |
| [K-Dense scientific skills `49c6e97`](https://github.com/K-Dense-AI/scientific-agent-skills/tree/49c6e97775eaa18ba791bebe23162a70ae601c18) | Metadata-preserving specialist import, conditional single-cell/statistical procedure selection | No whole-library install, implicit package setup, provider invocation or transmitted project data |
| [harness-100 `8e8d35c`](https://github.com/revfactory/harness-100/tree/8e8d35c6a19166614d1af1df85512266d51121ae) | Domain procedure selection, experiment tracking/comparison and diverse evaluation cases | No fixed domain team or assumed tracking service |
| [harness `cceac68`](https://github.com/revfactory/harness/tree/cceac68ea1d0ad198ef4b7b906cd238375836387) | Incremental producer/consumer, lifecycle and cross-component QA | Native Codex permissions and bounded reviews; no mandatory model, new agent or per-run topology rewrite |

Domain references are loaded conditionally: [scientific procedures](../.agents/skills/harness/references/scientific-workflows.md), [contract review](../.agents/skills/harness/references/contract-review.md), and [external skill selection](../.agents/skills/harness/references/external-skills.md). No manifest, authoring, transaction or artifact schema changed. Existing compatible project harnesses remain usable; run `config` for a reviewed instruction update without resetting them.

Tests establish file preservation, import conflicts, metadata discovery and existing generation/update behavior. They do not measure better scientific decisions, native discovery or token savings. Use the [generation evaluation protocol](../.agents/skills/harness/references/generation-quality-evaluation.md) for those separate questions.
