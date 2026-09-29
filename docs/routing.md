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

Official packages are downloaded from `openai/codex`, checked against GitHub's asset SHA-256, extracted within bounds, and started with `--version`. Before the atomic pointer switch, the staged candidate must also advertise the authenticated remote interface and pass app-server initialization and the model-catalog check. A failed or timed-out probe leaves the current package active and removes the new staging directory. This is an installation check, not a per-request operation or proof of all future TUI behavior. No Rust compilation or patched Codex binary is involved. Harness uses published releases, including beta releases; development branch commits are not normal automatic updates. Explicit branch pins retain the developer source path for `harness-codex update`.

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

An explicit native `--profile`/`-p` selection runs the original Codex terminal with the original arguments and a short notice that Harness Auto is unavailable for that launch. The current external app-server interface cannot preserve the selected profile's full configuration contract; Harness neither discards it nor flattens it into higher-priority permission overrides. To use Auto, launch without this explicit profile selector. Help (including `codex resume --help`), native utility commands and explicit `--remote` connections bypass update checks and the adapter. See [official profile configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#profiles).

Routing uses the current request, advertised model catalog and a small in-memory continuation context. Clear complex work can raise the tier immediately; two clearly lighter requests permit lowering it. Ambiguous continuations retain the current pair. “New task:” or “다음 작업:” allows immediate reassessment. Resume seeds its context from native saved inference settings, not a replayed transcript. These are deterministic preferences, not measured performance rankings.

There are no built-in model-ID preferences. Without a user preference file, Auto retains an available continuation model or uses the catalog's recommended default. It does not infer speed or quality from model names or list order. Known effort meanings (`low`, `medium`, `high`) remain task preferences only, never an availability allowlist: each selection must be advertised by that model, otherwise its supported default is used. New effort names are accepted without a source edit. User preference IDs remain explicit configuration, not built-in assumptions; an advertised `upgrade` can resolve a no-longer-visible preference when the catalog includes its successor information.

Catalog pages are bounded and combined at launch, when the native model menu requests them, and before the next request after a model/effort availability error. Ordinary turns reuse metadata and make no extra routing-model call. CLI versions and server-side catalog changes are independent. Resume reads metadata only (`thread/read`, without turns); when a server omits saved inference metadata, settings returned by resume are checked before the next task. Auto replaces unavailable selections with a supported catalog default and displays a warning. Manual selections require a new `/model` choice; if resume cannot open, use `codex --model AVAILABLE_MODEL resume SESSION_ID`. A failed inference request is never automatically replayed. Empty catalogs and missing usable defaults request a manual selection/native mode rather than inventing a model. Major protocol changes can still require a Harness update.

Image-containing, image-only and oversized text requests keep the current native inference settings. The 32 KiB routing bound does not truncate or reject their content. Optional preference files use real visible catalog model IDs:

```json
{"fast":["YOUR_AVAILABLE_FAST_MODEL"],"balanced":[],"deep":["YOUR_AVAILABLE_DEEP_MODEL"]}
```

```bash
harness-codex config --auto-model auto --routing-profiles models.json
```

## Optional outcome-based Auto advice

Adaptive evidence is separately opt-in per selected Harness workspace; existing
opt-outs and manual model choices are preserved. It makes no extra model call and
does not run paid comparison trials. Enable it before starting/resuming Codex:

Interactive `init` offers this preference with a short explanation after setup.
Enter preserves the current choice (off for a new project). For an explicit
choice, use `init --adaptive on` or `config --adaptive on`; the standalone
`routing --adaptive on|off` command changes it without regenerating the harness.
This option does not select `/model Auto`, replace ordinary routing when off,
or change manual model choices. Quality feedback is still required before
observations can support performance advice.

```sh
harness-codex routing --adaptive on
harness-codex routing --adaptive status
harness-codex routing --feedback work-item:OPAQUE_ID --outcome verified --source verification
harness-codex routing --feedback work-item:OPAQUE_ID --outcome failed --source verification --cause inference
harness-codex routing --adaptive off
harness-codex routing --adaptive clear --yes
```

Completed observed Auto and manual turns contribute duration and, when a reliable
native cumulative baseline is available, a token delta. Unknown token usage stays
null. The first resumed turn may lack that baseline; the native last-model-call
usage is never mislabeled as the whole turn. Completion alone leaves quality
unknown. Images, oversized routing requests, interrupted/failed native turns and
mixed-inference turns do not become efficiency evidence. Overlapping requests,
delegation/compaction and a harness revision change during a turn also exclude
that turn. Resume/fork discard any older usage baseline. Steering an active turn
(including image/oversized follow-ups)
also excludes it. Changed per-request execution settings wait for native acceptance
before later observations; rejected requests never become settings. One-turn service
tier, structured-output/tool-output overrides and legacy collaboration modes remain
outside comparable evidence. Ordinary routing and native request fields are preserved.
Duration includes tool and approval delays and is not a pure model speed measurement; tokens are not a
billing total.

Existing operations annotations with external verification/user evidence can
update the same observed work item. `--routing-cause inference` is required before
a negative result counts against a model. Environment/authentication/network
failures and unknown causes never do. Do not infer quality from reassuring prose
or generate a model-based rating after every conversation.

Advice groups evidence by workspace, harness revision, actual runtime version,
catalog revision, observed provider/service tier/permission settings, task category
and routing tier. Missing provider metadata leaves ordinary routing active without
collecting comparable performance evidence. Model/reasoning names are hashed
in local records and matched to the current advertised catalog in memory. A new
catalog/runtime/revision starts without transferable performance confidence.
Unrated models keep the ordinary rule/profile/default behavior; no universal model
ranking or causal benefit is claimed. Existing profiles still limit candidates.

Within a matching group, an alternative needs a quality confidence bound above
the configured floor and a sufficiently clear token/duration improvement without
a material measured regression. A reliably poor incumbent can yield to an
externally verified alternative even if that alternative costs more. Active tasks
require a larger gain; ambiguous continuations keep their choice. The next turn
can use advice; running turns and permissions are unchanged. Corrections replace
the work item's feedback, duplicates do not add confidence, and old evidence ages
out. There are at most 256 local samples and no raw prompts or transcripts.

Use `--adaptive-policy policy.json` to adjust `qualityFloor` (default 0.8),
`confidence` (0.95), `minimumGain` (0.15) and `historyDays` (30), inside validated
limits. Statistical bounds are conservative heuristics over observational data,
not proof that differently worded tasks have identical difficulty. Inspect with
`--adaptive status`; use isolated paired evaluation for a causal claim.

## Compatibility and removal

Before connecting, Harness checks for the official remote interface and a usable model catalog. If those checks fail it offers native mode or exit. Unexpected protocol failure stops the adapter and directs the user to resume; it never silently resubmits a request. Capability checks do not prove all future APIs, account restrictions or live tool behavior. Linux CI uses real official TUI and app-server processes with a synthetic local model provider, not paid inference.

Confirmed uninstall removes unchanged owned entry points, preferences, packages and exact PATH blocks. Edited or unknown files are preserved for review. Native history, authentication, standalone Codex and project harnesses remain intact. Windows integration releases remain paused; retained legacy build sources are not part of the Linux publication workflow.
