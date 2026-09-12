# Harness conversation UI and automatic inference settings

This is an opt-in terminal client for the installed Codex App Server. It is not a
patch to the original Codex CLI. Existing `new` and `resume` commands keep their
native screen unless `--ui harness` is supplied. Codex still executes tools,
enforces permissions and stores conversation history using its native login.

```bash
harness-codex new --ui harness --settings auto
harness-codex resume --ui harness
harness-codex resume SESSION_ID --ui harness --settings auto
```

No separate OpenAI API key is required by Harness. The installed Codex must be
authenticated and support the App Server methods used here. Native account and
model access restrictions still apply.

## Model menu

Enter `/model`. The first choice is **Auto**, followed by keeping native settings
and the visible models from `model/list`. Choosing a model opens its supported
reasoning choices. That pair stays fixed until Auto is selected again. Arrow keys
and Enter work on supported terminals; limited terminals use numbered choices.

`--settings auto` selects per-request routing in this UI. `--settings native`
supplies no model or effort overrides. Without the flag, the menu opens first.
The original CLI and configuration commands retain their previous settings
semantics: their `auto` chooses initial defaults, not per-request routing.

## Routing policy and boundaries

The selector does not call another model, rescan the project or copy conversation
history. It uses the current request and bounded in-memory task state. Known narrow
text edits can use the fast tier; uncertain scope stays balanced; selected complex
changes and repeated reported task failures request deep reasoning. A continuation
retains its previous supported pair unless escalation is justified. A short
"continue" message therefore does not downgrade a difficult active task.

The initial policy prefers `gpt-5.6-luna`, then `gpt-5.3-codex-spark`, for fast work;
the visible recommended default for balanced work; and `gpt-6-astra` for deep work.
These are explicit, replaceable policy choices informed by model guidance, not
learned rankings, pricing data or proof of superior performance. Unavailable
preferences fall back to a visible default or the current available model. New
unknown models are not ranked by their names or catalog order. Desired efforts are
low, medium and high respectively; a supported advertised default is used when
the desired level is unavailable. Missing capability metadata leaves native
settings unresolved rather than inventing a supported pair.

The initial classifier is conservative and rule-based in English/Korean. It can
misclassify work and is not a semantic complexity oracle. For an unrelated task,
use `/task TEXT`, or `/done` before the next request, to permit a downgrade. Otherwise
the previous task remains active. A completed Codex turn is not proof the whole
task passed its tests. `/failed` records a verified failure without rerunning work.

The chosen model, effort and reason are shown before execution. Only `model` and
`effort` are sent as routing overrides. No permission policy, sandbox setting,
approval reviewer, agent roster, project manifest or Git authorization is changed.
Custom subagents retain their own native configuration; selecting the parent
model does not rewrite or restart children.

An optional JSON file can replace preferences for any tier:

```json
{
  "fast": ["gpt-5.6-luna"],
  "balanced": ["gpt-5.6-sol"],
  "deep": ["gpt-6-astra"]
}
```

```bash
harness-codex new --ui harness --settings auto --routing-profiles /path/to/models.json
```

Only models actually present in the visible catalog may be selected. Files are
read as user input; Harness neither creates them nor executes content from them.
There is no separate routing session database. After resume, the native saved
model and effort anchor the task; in-memory failures and manual/auto mode are not
reconstructed from private transcripts. Use `--settings auto` or the menu again.

## Commands and recovery

| Input | Effect |
| --- | --- |
| `/model` | Auto first, or a fixed model/effort pair |
| `/status` | Last selection, native session ID and reported token usage |
| `/task TEXT` | Start an explicitly separate task in the same conversation |
| `/done` | Mark the current task complete without sending a model request |
| `/failed` | Record a verified failure in memory; do not retry |
| `/paste` | Multiline input, ending with `/end` on its own line |
| `/native` | Continue the same saved conversation in the original Codex CLI |
| `/quit` | Exit and preserve native conversation history |

The first project activation is combined with a real user task; opening and closing
an empty screen creates no conversation or bootstrap model turn. Ordinary resume
adds no activation turn. `--reload-harness` and source drift can request a re-read
with the next actual task. Resume omits historical turns from the client response,
while Codex retains them for the model; `/native` opens the original history view.
Conversation picker/`--last` operate on the selected
project; an explicit UUID can use its saved project directory.

Text replies stream live. Commands, file-change status, approval previews and user
questions remain visible. Native reasoning internals are not displayed. Long
command output is shortened in this view, while native history retains it. No
approval preview is silently truncated. The UI never auto-accepts native approval
requests and never retries a rejected request with broader permissions.

Ctrl+C during a turn requests native interruption and waits for acknowledgment.
`--turn-timeout SECONDS` sets a turn deadline (default 1800). A failed connection
or uncertain acknowledgment closes the client and displays a native resume command;
the original prompt is not resubmitted automatically. Inspect partial work before
retrying. At the input prompt, Ctrl+C exits.

This first UI supports text and multiline paste, not every native screen feature.
Attachments, the native prompt editor, hook trust management, plan/personality
menus and background-agent navigation use `/native`. Unsupported slash commands
are reported locally and are not forwarded to the model as ordinary prompts.
Parallel use of the same live conversation in multiple clients is unsupported.

Input requests are bounded to 32 KiB; reference project files for larger context.
This is a terminal request limit, not a new limit on project source files or the
`--goal-file` installation brief.

## Read-only preview and validation

```bash
harness-codex routing "Fix the README wording."
harness-codex routing "Continue." --continue-task --previous-tier deep \
  --previous-model gpt-6-astra --previous-effort high
harness-codex routing "Review concurrency." --catalog models.json --json
```

Preview queries native model metadata only, or reads a supplied complete
`model/list` JSON response offline. It never changes a session or runs a model.
An offline catalog cannot establish current account access. JSON output excludes
the prompt and distinguishes selection time from task time. No routing logs or
raw transcripts are retained by Harness; Codex owns its usual native history.

Deterministic scenario tests and subprocess protocol tests validate selection,
same-thread continuity, manual pinning, permission preservation and failure paths.
They do not prove quality, token savings, lower billing or faster task completion.
Those require representative paired tasks, including failures and rework, against
a fixed-model baseline. This feature remains experimental until that evaluation.

Protocol sources: [App Server](https://learn.chatgpt.com/docs/app-server),
[native model command](https://learn.chatgpt.com/docs/developer-commands?surface=cli),
[custom-agent settings](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[model guidance](https://developers.openai.com/api/docs/guides/latest-model).
