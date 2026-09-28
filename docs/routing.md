# Official Codex with Harness Auto

```bash
harness-codex init --goal-file PROJECT.md
source ~/.bashrc
codex
codex resume
codex resume --last
```

The Linux `codex` entry checks published updates, then launches the unmodified official terminal. Its original renderer connects to a loopback adapter, which relays to the same official executable's app-server. Authentication, history, tools, approvals and sandbox enforcement remain in Codex. No activation prompt or extra work conversation is created by Harness.

## Updates without rebuilding Codex

Official Codex and Harness have independent version pointers. Every interactive launch queries both published release channels with a short network timeout. Available updates appear before the conversation, with arrow-key choices to update both, either tool, or skip. No model request or token usage is involved. The default choice is skip. Offline checks retain installed versions.

Official packages are downloaded from `openai/codex`, checked against GitHub's asset SHA-256, extracted within bounds, and started with `--version` before an atomic pointer switch. No Rust compilation or patched Codex binary is involved. Harness uses published releases, including beta releases; development branch commits are not normal automatic updates. Explicit branch pins retain the developer source path for `harness-codex update`.

```bash
codex update                 # Explicitly update the owned official Codex package
harness-codex update --check # Check published Harness releases
harness-codex update         # Explicitly update Harness
HARNESS_NO_UPDATE_CHECK=1 codex
HARNESS_CODEX_NATIVE=1 codex  # Official UI without the Auto adapter
```

Use the same public installer with `--existing reuse`, followed by `config`, for the initial migration from the old patched binary. Original standalone Codex installations and old owned packages are preserved. A separately installed npm Codex is not overwritten; the owned integration uses its independently updated official package. Exit and reopen the shell if it still resolves the old PATH.

## Auto selection and its limits

`/model` includes **Auto**. Regular model and reasoning selections disable it. The adapter changes only model/effort fields for a new turn. It does not change permissions, switch a running turn, alter subagent configuration, or retry tasks. Display-only aliases let the official footer identify Auto and the selected real model/reasoning. A custom status line needs a native model item to show this. Older Codex renderers may show the alias ID instead of the friendly Auto label. The release gate requires the current official Linux renderer to show the full menu/routing/footer behavior; arbitrary future renderer compatibility is not guaranteed.

`init/config --auto-model auto` enables Auto by default. `--auto-model manual` retains native defaults. A bounded user-local record keeps each thread's Auto or manual preference for resume; it contains no prompts or transcripts. Explicit `--model` starts with the requested manual choice. Global Codex defaults are not rewritten when selecting Auto.

Routing uses the current request, advertised model catalog and a small in-memory continuation context. Clear complex work can raise the tier immediately; two clearly lighter requests permit lowering it. Ambiguous continuations retain the current pair. “New task:” or “다음 작업:” allows immediate reassessment. Resume seeds its context from native saved inference settings, not a replayed transcript. These are deterministic preferences, not measured performance rankings.

Image-containing, image-only and oversized text requests keep the current native inference settings. The 32 KiB routing bound does not truncate or reject their content. Optional preference files use real visible catalog model IDs:

```json
{"fast":["gpt-5.6-luna"],"balanced":["gpt-5.6-sol"],"deep":["gpt-6-astra"]}
```

```bash
harness-codex config --auto-model auto --routing-profiles models.json
```

## Compatibility and removal

Before connecting, Harness checks for the official remote interface and a usable model catalog. If those checks fail it offers native mode or exit. Unexpected protocol failure stops the adapter and directs the user to resume; it never silently resubmits a request. Capability checks do not prove all future APIs, account restrictions or live tool behavior. Linux CI uses real official TUI and app-server processes with a synthetic local model provider, not paid inference.

Confirmed uninstall removes unchanged owned entry points, preferences, packages and exact PATH blocks. Edited or unknown files are preserved for review. Native history, authentication, standalone Codex and project harnesses remain intact. Windows integration releases remain paused; retained legacy build sources are not part of the Linux publication workflow.
