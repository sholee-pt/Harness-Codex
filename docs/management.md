# Management inside Codex

The ordinary `harness-codex` commands remain available. When `codex` starts through
the Harness integration, type a qualified command such as `/harness/status` in
the composer. Use `/harness/` for a small management menu.

These commands use the unmodified Codex terminal and the local protocol adapter.
They are **not built-in slash commands**: `/harness-status` is not supported and
the native `/` completion menu does not list them. The qualified `/harness/`
namespace currently passes native input validation. Future parser or protocol
changes may require an adapter update; capability probes and the Linux release
gate do not guarantee every future Codex version. Native mode, explicit native
profiles, and a standalone Codex launch without the adapter use terminal
`harness-codex` commands instead.

## Commands

| In the Codex composer | Effect |
| --- | --- |
| `/harness/status` | Local status box: version, author, project, maintenance, adaptive routing, Jev, Graft and hook registration. No inference request. |
| `/harness/settings` | Native question picker for maintenance, adaptive Auto and exact owned hook trust. Does not regenerate project artifacts. |
| `/harness/init --goal "Project purpose"` | Install the generator, refresh skill metadata and ask the current conversation to configure a missing harness. An existing manifest is reported instead of replaced. |
| `/harness/init --goal-file "PROJECT.md"` | Reference a Markdown brief relative to the selected project. Its full text is not copied into a bootstrap prompt. |
| `/harness/config` | Refresh the owned generator and ask the current model to review existing artifacts. Native permissions and approvals remain effective. |
| `/harness/maintenance` | Inspect local maintenance observations. |
| `/harness/maintenance review` | Explicit model request to review eligible concerns under the existing modes, leases and limits. Uses conversation tokens. |
| `/harness/routing` | Inspect local adaptive Auto evidence; does not select Auto in `/model`. |
| `/harness/routing --adaptive on` | Enable evidence-based advice; manual model choices remain manual. |
| `/harness/jev` | Inspect Jev mode and whether a credential is available. No authentication or inference request. |
| `/harness/jev disable` | Disable Jev for this project. Enter credentials only through terminal `harness-codex jev login`, never in conversation history. |
| `/harness/graft` | Inspect local retrieval settings. Does not rebuild the graph or establish freshness. |
| `/harness/graft add "PATH" --name LABEL` | Explicitly attach a narrow external source under the existing project-specific retrieval contract. |
| `/harness/doctor` | Run static project validation; does not establish live agent discovery or quality. |
| `/harness/switch` | Choose a reachable project from recent native conversation metadata. |
| `/harness/switch "PROJECT_PATH"` | Select another existing project and choose its resume picker or a new conversation. |
| `/harness/update --check` | Check the published Harness version; a network request, not a model request. |
| `/harness/update` | Check, then optionally queue the terminal updater after normal Codex exit. |
| `/harness/remove` | Preview and confirm unchanged owned project file removal, then separately offer empty component-directory cleanup. |
| `/harness/remove --include-generator` | Also include unchanged generator files in the preview. |
| `/harness/reset` | Confirm removal first; then explicitly use `/harness/init` to create a new design. Unlike terminal `reset`, this is a two-step workflow. |
| `/harness/help` | Management menu and command list. |

Status and settings use the same local implementations as the terminal commands:

```bash
harness-codex status --project /path/to/project
harness-codex settings --project /path/to/project --maintenance suggest --adaptive on
harness-codex settings --project /path/to/project --prepare-hooks
harness-codex switch --project /path/to/other-project
harness-codex switch --project /path/to/other-project --new
```

Local management output is labelled as such. It is displayed through Codex's
message renderer; it is not the built-in `/status` implementation or a model
answer. Local control turns are transient and are not added to native saved
conversation history. Configuration and explicit maintenance review are real
model turns and remain in that history. A status box cannot establish that
every skill loaded or that token use or task quality improved.

Successful in-conversation `init` validates files, refreshes the single owned
guide, prepares host diagnostics and optional retrieval, and attempts native
trust for exact Harness hooks. Preferences stay unchanged until selected through
`/harness/settings`. Missing Jev credentials require terminal login. `config`
does not automatically change retrieval, maintenance or hook-trust preferences.
New native agents may require a fresh conversation even after files validate.
If the model asks a clarification question, answer normally. Completion waits
for a changed manifest in the same conversation; unchanged turns only check its
file metadata and do not repeat validation or inference. Interrupted setup stops
this pending completion. Run `config` again to explicitly continue it.

## Project switching

A changed task within the same project normally needs only a new request. It does
not imply another agent or regeneration. For another project, `/harness/switch`
queues a separate native launch in the same terminal. Finish active agents and
background work, then use `/quit`. Harness does not interrupt them to switch.
The target launch reads its own root instructions, skills and agents. The
original conversation remains available through its native resume picker.

The target can resume a saved conversation, start a new one with an existing
harness, or start without a harness. In the last case, use `/harness/init` there
when generation is wanted. There is no automatic transcript copying or inherited
source-project permission override. To hand off information, explicitly provide
only the relevant summary in the target conversation. A missing mount path is
not rebound by guessing: provide the actual path on the current host. Queued
actions are in memory only, replaced by another queued action, and discarded on
a failed or interrupted native exit. Use `/harness/switch --cancel` or
`/harness/update --cancel` to clear the pending action while staying in Codex.
The target keeps the launching shell's environment; project switching does not
activate a different Conda environment automatically. Native menus retain native
keyboard handling, including Esc interruption; Harness does not intercept keys.

## Removing files and folders

Both interfaces retain the existing ownership, modified-file conflict and
transaction recovery checks. In-conversation confirmation is bound to the
reviewed removal plan; a later file change requires a fresh preview. After
successful removal, a second confirmation can remove **empty parents of the
removed files** under project `.agents`, `.codex`, and `.harness`. This does not
establish that every such directory was originally created by Harness; existing
empty component parents are included in the explicitly displayed scope.

Cleanup uses non-recursive directory removal. User files, unrelated empty
directories, the project root, account `.codex`/`.agents`, and `CODEX_HOME` are
preserved. JSON or redirected commands do not imply consent: terminal automation
must explicitly add `--cleanup-empty-dirs`. Removing instructions does not erase
them from an already running model's context; begin a fresh conversation before
continuing work without the removed harness.
