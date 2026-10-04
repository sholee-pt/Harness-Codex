# Management inside Codex

The ordinary `harness-codex` commands remain available. When `codex` starts through
the Harness integration, type a qualified command such as `/harness/status` in
the composer. Use `/harness/` for a small management menu.

Default Linux installation prepares this integration before any project has a
harness. Apply the installer's PATH change in a new shell, run `codex` from any
existing working directory, and choose **Project → Init** in `/harness/`. Tool-only installs
(`--no-codex-integration` or `--no-modify-path`) skip that connection. Codex still
handles account login and project trust. Windows installation is unchanged while
its release path is paused.

## Guided setup

The menu shows the selected project and current after-exit reservation, then
groups related actions:

| Group | Actions |
| --- | --- |
| Project | Init, Config, Switch, Remove, Reset |
| Settings | Preferences, Jev, Graft |
| Diagnostics | Status, Doctor, Maintenance, Routing |
| Tools | Check updates, Update, Uninstall, Queued action |
| Help | Existing qualified command names |

Back returns to the containing menu; Back at the top returns to the conversation.
The existing qualified commands remain available directly. Init and Config
without arguments open a guided workflow:

1. Keep the current project or enter another directory. Relative directory paths
   are based on the current project; missing directories require final confirmation
   before creation. Mount paths are never guessed.
2. If a harness exists, inspect its status or explicitly review and update it.
   Generation does not silently reset an existing harness.
3. Enter a single-line description, enter a Markdown path, or select existing
   project evidence. Markdown paths are relative to the target project; contents
   are referenced instead of copied into a bootstrap prompt.
4. Review the project, action and brief, then confirm. Back revisits the previous
   input or selection; `:back` leaves a text input. Entered paths and descriptions
   remain available through **Keep entered value** or **Keep entered brief**.
   Briefs are retained separately for each selected project during this wizard.
   Native keyboard handling is unchanged.

Preferences displays the selected project, current maintenance mode, adaptive
Auto setting and recorded hook state. **Keep current** is the first option.
Selecting a different preference shows its current and proposed values before
**Apply change**. Selecting the current value makes no preference write. Back
from the value picker returns to preferences; Back from confirmation returns to
the value picker. Hook preparation still uses the native policy checks for only
the exact owned definitions.

Selection and status inspection make no model request. Confirmed configuration
uses a real turn with the current model, reasoning and permissions. If the target
differs from the conversation directory, finish active work and use `/quit`:
Harness opens a fresh target conversation and submits the approved configuration
there. A missing target is prepared only after normal exit. Source permissions,
transcripts and Conda activation are not copied. Interrupted or failed exit
discards the reservation. **Tools → Queued action** reviews or cancels the
displayed reservation. `/harness/switch --cancel` cancels only a project switch;
it does not cancel configuration, authentication, update or uninstall requests.

Jev's menu can queue private login/logout; **Tools** can queue updates or uninstall.
After `/quit`, the existing terminal flow starts automatically. Credentials are
never requested in conversation history, and uninstall retains its terminal
preview and confirmation. No additional CLI command needs to be typed, but these
flows execute after leaving Codex. Advanced terminal commands remain available.

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
| `/harness/status` | Local status box plus the current conversation's after-exit reservation. No inference request. |
| `/harness/settings` | Current project/preferences, Keep current default, then explicit change confirmation. Does not regenerate project artifacts. |
| `/harness/init` or `/harness/config` | Guided project, brief and confirmation steps. |
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
| `/harness/switch --cancel` | Cancel a queued switch only; retain other kinds of reservations. |
| `/harness/update --check` | Check the published Harness version; a network request, not a model request. |
| `/harness/update` | Check, then optionally queue the terminal updater after normal Codex exit. |
| `/harness/update --cancel` | Cancel a queued Harness update only. |
| `/harness/tool` | Update checks, update scheduling, terminal uninstall and queued-action review. |
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
every skill loaded or that token use or task quality improved. Successful local
controls complete normally, interrupted controls report `interrupted`, and local
operation errors report `failed` with an error message. If forwarding a real
model task is not confirmed, a separate warning requests checking the native
conversation before retrying; the adapter does not replay it automatically.

Successful in-conversation `init` validates files, refreshes the single owned
guide, prepares host diagnostics and optional retrieval, and attempts native
trust for exact Harness hooks. Preferences stay unchanged until selected through
`/harness/settings`. Missing Jev credentials require terminal login. `config`
does not automatically change retrieval, maintenance or hook-trust preferences.
New native agents may require a fresh conversation even after files validate.
If the model asks a clarification question, answer normally. Completion waits
for a changed manifest in the same conversation; unchanged turns only check its
file metadata and do not repeat validation or inference. Validation and optional
retrieval preparation run separately from the native response stream; subsequent
conversation events continue while they finish. Leaving the connection or
interrupting that setup cancels its pending subprocess work, including npm and
its installation children. A new configuration or confirmed removal first stops
the earlier completion. Run `config` again to explicitly continue interrupted setup.

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
actions are in memory only and discarded on a failed or interrupted native exit.
A different request displays the existing and requested actions, with **Keep
queued action** selected first; replacing it requires **Replace queued action**.
Choosing **Later** in update scheduling preserves an existing reservation and
reports what remains queued. `/harness/status` and the management menus display
the reservation. Use **Tools → Queued action** to cancel the displayed action of
any kind, or `/harness/switch --cancel` and `/harness/update --cancel` for their
respective kinds. These controls stay inside the current conversation.
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
