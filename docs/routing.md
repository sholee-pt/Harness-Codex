# Original Codex UI with Harness Auto

The optional Harness UI is a pinned build of **Codex CLI 0.154.0**, using the
original composer, text rendering, colors, animations, menus, shortcuts and
permission screens. Harness adds Auto to `/model` and a selector before new
requests. It does not maintain an imitation renderer. Terminal font, theme,
dimensions and native settings still determine the rendered appearance.

```bash
harness-codex new --ui harness --settings auto
harness-codex resume --ui harness --settings auto
harness-codex resume SESSION_ID --ui harness --settings native
```

The first launch fetches the matching native extension package, verifies release
checksums and stores it under the managed Harness tool directory. Subsequent
launches check the retained package and reuse it. Linux/Windows x86_64 are
supported by the extension; `--ui native` continues to use your installed Codex
on other architectures. No separate API key is introduced. Codex's existing
authentication, model access, project trust and approval settings apply.

Your separately installed `codex` command is unchanged. Without `--ui harness`,
Harness uses that installed command. The extension is not automatically rebased
onto future Codex releases: each upstream change requires a reviewed build and
tests, so its pinned version may differ from your standalone Codex.

## Auto and manual selection

In the conversation, type `/model`. **Auto** is the first item in the native
selection menu. Use the original arrow-key navigation and Enter to choose it.
Choosing a regular model and reasoning level disables Auto. Selecting Auto does
not change global Codex defaults, permissions or subagent configuration.

`--settings auto` enables per-request selection immediately. `--settings native`
and `--settings manual` begin with native saved/default inference settings; use
the original `/model` picker to select a pair. Omit the flag for an initial
Auto/Manual choice. Configuration commands retain their prior behavior:
`init/config --settings auto` selects initial defaults, not this per-request mode.

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
fallback. The native status line shows the current model; a brief native history
message reports a changed Auto selection.

A continuation keeps its pair unless escalation is justified. For unrelated
work, **reselect Auto** before entering the next request to reset task context and
allow a lower tier. This explicit boundary avoids treating “continue” as a new
easy task. A completed turn is not evidence that a task passed its tests. The
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
harness-codex new --ui harness --settings auto --routing-profiles models.json
```

Preferences cannot select hidden models or unsupported reasoning levels.

## Session behavior and package maintenance

Native slash commands, attachments, history, streaming, interruption, keyboard
shortcuts and approval interfaces stay in the original TUI. There is no separate
Harness `/task`, `/done`, `/failed`, `/paste` or `/native` command. To use your
standalone Codex later, exit and run `harness-codex resume SESSION_ID --ui native`.
Do not operate the same conversation concurrently in two terminals.

Ordinary resume adds no activation turn. `--reload-harness` and source drift can
add the same bounded re-read request used by native Harness sessions. New
conversations retain the existing project activation workflow; this extension
does not claim that opening native Codex creates no session or no initial turn.
The generator, project harness and native UI component have separate lifecycles.
Updating the tool never resets a project harness.

`harness-codex update` updates the generator/CLI. The next `--ui harness` launch
fetches that release's native component if needed. Unknown or changed package
files are preserved and reported. Confirmed `harness-codex uninstall` removes
unchanged owned components along with the tool; project harnesses and standalone
Codex remain available.

For offline or authenticated release downloads, verify `SHA256SUMS`, then use:

```bash
harness-codex new --ui harness --settings auto \
  --native-ui-archive harness-codex-ui-0.12.0-beta-linux-x86_64.tar.gz
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
