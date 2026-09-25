# Native Codex with Harness Auto

`codex` resolves directly to a verified, Harness-managed build of the original
Codex CLI 0.154.0. A bounded extension adds Auto to the original `/model` menu.
There is no separate conversation UI, session manager or Python launcher.

```bash
harness-codex init --goal-file PROJECT.md
# Press Enter after init to load ~/.bashrc in a new Bash, then:
codex
codex resume
codex resume --last
```

The original renderer, composer, animations, colors, shortcuts, slash commands,
attachments, permissions, authentication and native history remain Codex-owned.
The current integration release supports Linux x86_64; Windows releases are paused. Other architectures can
use a separately installed Codex with `init --no-codex-integration`, without Auto.

## Integration design and original Codex preservation

The documented plugin and hook interfaces provide skills, tools and additional
context, but no documented model-picker item registration plus per-turn model
setter. The pinned original build therefore supplies the menu/inference extension.
See [Codex plugins](https://learn.chatgpt.com/docs/plugins) and
[hooks](https://learn.chatgpt.com/docs/hooks).

`init/config` verify the matching package and register its versioned `bin`
directory on PATH. The native executable discovers a bounded routing sidecar
beside its package. The sidecar names the isolated interpreter and hash-bound
selector; the management tool records its ownership. Ordinary `codex` invocation
does not launch the Harness CLI or inspect the complete project manifest.
Auto invokes the local selector only before eligible turns.

No original Codex executable is overwritten. Its detected location is recorded.
No credentials, settings or conversation history are copied into a Harness home.
On Bash, one exact managed block is registered in `.bashrc`. On Windows, one
owned directory is prepended to the user PATH. Apply the change in a fresh
terminal; `doctor` reports when PATH still resolves another Codex. A shell alias,
function or Windows machine PATH entry can take precedence over this registration;
review that precedence explicitly instead of overwriting an original installation.

There is no argv forwarding layer: native `codex resume`, `exec`, other commands,
standard streams, terminal ownership and exit status go directly to that executable.
The pinned version may lag a separately installed upstream Codex; updating upstream
requires review and testing of a new extension build.

This build revision is reproducibility metadata, not a runtime version gate. Project
skills and current runtime observations use available capabilities and validated
event shapes. Updating a separately installed Codex does not automatically add the
Auto UI patch to that executable; use it directly without integration, or select a
verified extended package. Unknown event shapes reduce observability instead of
pretending that native execution failed or silently broadening permissions.

## Auto and manual selection

In the conversation, type `/model`. **Auto** is the first item in the native
selection menu. Use the original arrow-key navigation and Enter to choose it.
Choosing a regular model and reasoning level disables Auto. Selecting Auto does
not change global Codex defaults, permissions or subagent configuration.

`init/config --auto-model auto` enables selection on subsequent native launches.
`--auto-model manual` retains native saved/default settings until Auto is selected.
This is a Harness-owned default, not a global Codex preference change. Manual
selection in `/model` disables Auto for that widget. `--settings` continues to
control initial settings of the separate generation operation only.

The selector reads the current request and bounded in-memory context. It does
not call a routing model, scan project files or process the whole transcript.
Known narrow edits can use the fast tier; uncertain tasks stay balanced; selected
complex tasks use deeper reasoning. It checks the actual visible model catalog
and each model's supported reasoning levels. Image requests exclude models that
do not advertise image support. Restricted native account choices remain
restricted.

The initial preferences are Luna, then Spark, for fast work; the native default
for balanced work; and Astra for deep work. These are explicit policy choices,
not learned performance rankings. Unavailable preferences use a supported native
fallback. The native model footer shows `Auto selected: MODEL REASONING` immediately
when Auto is enabled, including when the selection stays unchanged. Choosing a
manual model restores the ordinary model label. A brief native history message
reports a changed Auto selection. A custom status line with no model item remains
unchanged; add `model-with-reasoning` through native `/statusline` to see the label.

A continuation such as “continue” keeps its pair unless escalation is justified.
Recognized complex work can raise the tier immediately. Clear scoped code requests
can move from fast to balanced. Two consecutive clearly lighter requests allow a
lower tier; an ambiguous continuation interrupts that pending change. Starting a
request with “New task:” or “다음 작업:” permits immediate reassessment, including
a lower tier. Reselecting Auto also resets the task boundary. The selector retains
only one pending counter alongside the current pair, not previous request text.
A completed turn is not evidence that a task passed its tests. The
extension does not infer a failure count or claim task success from conversation
text. Auto state is local to the active conversation widget; resume/new-thread
settings and the `/model` choice determine whether it is enabled there.

The local selector is bounded to three seconds and 32 KiB of request text.
Larger requests still go to native Codex with its current inference settings;
they are not truncated or rejected by Harness. Selector failure also retains
native settings and reports an error. No task is retried automatically, and
steering an already running turn never switches its model mid-execution.

Optional preference file:

```json
{"fast":["gpt-5.6-luna"],"balanced":["gpt-5.6-sol"],"deep":["gpt-6-astra"]}
```

```bash
harness-codex config --auto-model auto --routing-profiles models.json
```

Preferences cannot select hidden models or unsupported reasoning levels.

## Native history, updates and removal

Native history replay initializes continuation context from the saved native
model and reasoning level. It never inserts a Harness activation message. A clear
new-task prefix or Auto reselection permits an immediate lower tier. Auto state remains in memory, and the installed
manual/auto default governs a newly opened widget. It does not create a second
session database or guarantee that an old Auto toggle persists across processes.

`harness-codex update` updates the tool and an existing integration to the matching
native package. Project harness changes require `config`. Verified older native
packages are retained so existing processes are not replaced in place. Unknown or
changed files block destructive updates/removal. If integration setup fails after
a tool update, the previous registered native package remains available; retry the
update or use `config` after resolving the reported issue.

Confirmed `harness-codex uninstall` removes unchanged owned packages, sidecars and
their PATH registration. A fresh shell then resolves the original Codex again,
provided it remains installed and on the user's independent PATH. Project harnesses,
native history, credentials and original binaries are preserved. An edited PATH
block or concurrent PATH change is preserved and can block removal for review.

For verified offline packages:

```bash
harness-codex config --native-ui-archive harness-codex-ui-0.23.0-beta-linux-x86_64.tar.gz
```

The component includes official same-version helper binaries, file fingerprints,
the upstream Apache-2.0 license and notices. Only the Codex entrypoint is replaced
with the extended build. The build pins upstream source and dependency checksums;
Linux also embeds the exact bundled sandbox-helper digest.
Hosted builds disable link-time optimization and debug symbols to bound builder
memory use; runtime source and native permission behavior are unchanged.

## Preview and validation

```bash
harness-codex routing "Fix the README wording."
harness-codex routing "Continue." --continue-task --previous-tier deep \
  --previous-model gpt-6-astra --previous-effort high
harness-codex routing "Review concurrency." --catalog models.json --json
```

Preview reads model metadata only; a supplied complete catalog works offline.
It does not change a session or run a model. Harness retains no raw routing
transcript. Codex retains its normal native history.

The rule policy can misclassify work. Unit tests, native UI snapshots and build
checks establish behavior and integration boundaries, not model quality, token
savings or billing savings. Those require representative paired tasks including
failed attempts and rework. Changing models within one conversation preserves
native history but can change instruction adherence, style or task decisions.
It does not retrain agents or improve the harness automatically.

Source: [pinned Codex CLI](https://github.com/openai/codex/tree/6b9826e3aa83b1a5947db50f4332cb9c65f1b340),
[App Server](https://developers.openai.com/codex/app-server/).

A single explicit documentation typo stays lightweight even when its subject is security or architecture. Mixed code/review requests retain the risk-sensitive classification. CLI version strings are not model selection inputs; use the current visible model catalog and supported reasoning options.
