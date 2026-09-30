# Optional Jev retrieval advice

Jev can classify candidates already returned by a Graft query. Successful `init`
automatically enables its shadow comparison after Graft is ready. It requires a
separate TypeSafe API key for actual requests. On Linux, interactive init offers
guided key setup when none is available. Existing credentials make no init API
calls; entering a new key permits one small, fixed authentication request.

Initialize normally; no separate `jev enable` command is needed:

```bash
# Follow the key setup prompt, or skip it and continue without Jev calls.
harness-codex init --project /path/to/project
harness-codex graft query "Where is request validation implemented?" --project /path/to/project --json
harness-codex jev status --project /path/to/project --json
```

This requires a TypeSafe account/key independently of Codex authentication.
Without a key, Jev remains configured and Graft returns its ordinary results.
Running `jev login` or setting `TYPESAFE_API_KEY` later enables eligible calls
without another init or enable command. Init reports the external processing
boundary. Credentials never enter project settings or process arguments.
Requests use the fixed HTTPS TypeSafe endpoint;
redirects are rejected. The provider receives the query and up to 2,400 characters
per returned candidate, including source pointers and code excerpts. Its data
handling policies apply. No full conversation, graph or extra source files are
sent. Do not enable this for projects whose retrieved source cannot be shared.
Use `init --retrieval off` to skip both retrieval setups, or run `jev disable`
after init to retain local Graft without Jev. No model request occurs in between
unless you run an eligible retrieval query. Existing Jev preferences, including
explicit disable/clear, mode, model, budgets, caches and labels, survive repeated
init without state writes. `jev enable` explicitly re-enables a disabled setup. Config
and reset preserve Jev preferences. Dry-run, install-only, failed configuration
and disabled/unavailable Graft never initialize Jev.

## Login and saved credentials

Pressing Enter requests a new browser tab through the environment's browser
connection. This includes an inherited `BROWSER` opener (used by VS Code Remote)
or a forwarded graphical display. It is not tied to VS Code, Chrome or a terminal
brand. In plain SSH sessions from PuTTY, MobaXterm or PowerShell without such a
connection, open the displayed `https://console.typesafe.ai/keys` address on your
own computer and paste the key into the hidden terminal prompt. A failed or
timed-out opener also shows this fallback; a sent request does not prove a tab
appeared. No login callback server is started, so port forwarding is not required
for this key-paste flow. Existing keys are reused without opening a browser.

On Linux, init prints the official [key page](https://console.typesafe.ai/keys).
Press Enter to try opening it, `p` to paste directly, or `s` to skip.
Sign in and issue a key on TypeSafe,
then paste it into the hidden terminal prompt. An empty key skips setup; a
terminal that cannot hide input is refused. JSON/unattended runs never prompt
or open a browser. This is API-key setup, not OAuth or automatic key issuance.

One four-second-bounded request checks the newly entered key using a fixed test
sentence, with no project data. This can incur a small provider charge, disclosed
before input. A 401 rejection preserves any previous key. Network/service failures
save the entered key as unverified in the setup result; they are not reported as
successful authentication. Subsequent eligible requests still use the normal
timeout, budget and fallback. Authentication checks are separate from project
retrieval counters and limits. Existing credentials are reused without probing.

```bash
harness-codex jev login                    # Also works before project init
harness-codex jev login --replace-key      # Replace a saved key explicitly
harness-codex jev logout                   # Confirm removal with yes
```

`TYPESAFE_API_KEY` takes precedence and is never copied into storage. Otherwise,
Harness reads `~/.local/share/harness-codex-credentials/typesafe.json` directly.
`HARNESS_CREDENTIAL_HOME` can select a different user-owned storage directory.
Linux enforces directory 0700 and file 0600, current-user ownership, a bounded
regular file and no symbolic/hard links. Foreign, malformed or overly accessible
files are preserved and not used. The file is plaintext with restricted access,
not an encrypted keyring. Keys never enter `.bashrc`, a project, a manifest,
observations, logs or command arguments. No `source` or terminal restart is needed;
projects on the same machine and OS account reuse the key. Project opt-outs remain
independent. Windows persistent login is not provided while Windows work is paused;
environment keys remain supported.

Logout removes only the owned saved credential, leaves project settings intact,
and cannot unset a parent shell's environment key. `jev logout --yes` supports
explicit unattended removal. Confirmed tool uninstall also removes the owned
credential; unsafe/unrecognized storage is preserved and reported. Clearing Jev
observations or reinstalling/updating the tool does not remove the credential.

## Selective calls and preserved behavior

- Only an actual `graft query` can send retrieval candidates to Jev. The sole
  additional call is the fixed probe after explicit new-key entry. Configuration,
  ordinary turns, the native Auto model selector, status, repeated init with a key
  and disabled retrieval do not call it.
- A query needs 6-20 distinct candidates, a 20-8,000-character question and a
  request body no larger than 48,000 bytes. These are conservative eligibility
  rules, not proof that a judgment is necessary or beneficial.
- One request batches all candidate judgments. There are no per-candidate calls,
  generation calls or retries on the request path. The default ceiling is 20
  attempted calls per project per UTC day; `--daily-calls` accepts 1-100. Separate
  projects have separate limits, so this is not an account-wide spending cap.
- The child process has a four-second total deadline. A failed call reserves its
  budget and starts a five-minute cooldown. Missing keys, invalid responses,
  unavailable state, occupied locks and exhausted budgets preserve normal results.
- Identical query, candidates, policy and pinned model reuse advice for 24 hours.
  Changed snippets or model versions invalidate reuse. At most 128 entries remain.
  No graph refresh is added by Jev; Graft keeps its own source-change check.

The default **shadow** mode returns exactly the original Graft text. JSON also
contains `jev.queryId`, `suggestedOrder` and yes/no/abstain judgments. Candidate
`c0` is original hit 1, `c1` is hit 2, and so on. Probabilities at least 0.8 become
yes, at most 0.2 become no, and the middle band abstains. These thresholds are
policy heuristics, not calibrated accuracy. A negative answer never removes a hit.

After comparing suggestions with source inspection, optionally expose a reading
order hint to the agent:

```bash
harness-codex jev enable --project /path/to/project --mode suggest --daily-calls 20
```

Suggest mode adds one compact hint when it fits the existing output limit. All
original text and candidates remain. Yes, abstain and no bands preserve original
order within each band. The advice does not choose permissions, apply changes,
approve tests, add agents, select a Codex model or authorize commit/push. Untrusted
source instructions or confidently incorrect judgments can still mislead a model;
source inspection and normal verification remain necessary.

## What is actually evaluated

After activation, local counters automatically record attempted calls, failures,
cache hits, call latency and provider-reported input/output tokens from valid
responses. Failed or interrupted calls can also be billed without returning usage.
These counters measure added overhead, not saved Codex tokens or improved quality.

Review a query's original numbered hits against the source, then supply the
relevant IDs. Feedback is optional and must reflect external review, not Jev's
own answer being treated as ground truth:

```bash
harness-codex jev feedback --project /path/to/project --query-id QUERY_ID --relevant c2,c4
# Or --relevant none when no returned candidate was useful.
harness-codex jev status --project /path/to/project --json
```

Status compares baseline and suggested mean reciprocal rank: the average inverse
rank of the first relevant result, zero if none is relevant. Feedback replaces
an earlier label for the same query; retained labeled queries are counted once.
These are results on a small, user-selected, bounded cache, not an unbiased task
benchmark. Expiration/replacement, eviction, model changes and clearing can remove
labels. The report therefore retains `benefit: not-measured` for overall task
benefit and `automaticImprovement: false` even when ranking improves.

Harness, Graft and Jev do not jointly evaluate every conversation and rewrite
themselves in real time. [Existing maintenance](maintenance.md) allows separately
enabled, bounded corrections to existing project skills. It does not establish
causal performance benefit or automatically tune Jev/Graft. [Task evaluation](evaluation.md)
requires controlled comparisons. Compare ordinary search, Graft alone and
Graft plus Jev on equivalent tasks, keeping the Harness/model setup fixed; compare
Harness itself separately. Include failures, source correctness, total wall time,
all model usage, indexing and review costs. The shadow phase necessarily adds
observation cost and cannot demonstrate production savings by itself.
The existing paired evaluator does not automatically configure isolated Graft/Jev
arms or combine TypeSafe usage with Codex usage; those setup and accounting steps
must be explicit in the comparison.

## Local state and controls

State stays under the selected user's Graft storage, separate from project
artifacts, manifests and transactions. It contains keyed query fingerprints,
bounded probabilities, optional candidate-index labels and counters; no raw
questions, snippets, source paths, provider replies or API keys are persisted in
observations. Saved authentication lives separately in the credential directory.
Existing caches survive tool uninstall, matching Graft's documented behavior.

```bash
harness-codex jev disable --project /path/to/project
harness-codex jev clear --project /path/to/project --yes
```

Disable preserves observations. Clear disables Jev and removes cached advice,
labels and aggregate counters, preserving the current daily call reservation so
clearing cannot bypass its budget. OS advisory locks are released when their process exits; retained `.state.lock` files are not stale ownership and must not be deleted to bypass locking. A legacy `.install.lock` is removed automatically only when its recorded process is demonstrably absent. If legacy ownership cannot be determined, preserve it for review.

The reviewed default is the versioned `jev-1.13.0`; `--model jev-X.Y.Z` permits
explicit version changes with cache invalidation and strict response-shape/model
checks. Availability and behavior still require provider validation.

References: [TypeSafe API](https://docs.typesafe.ai/api),
[Noul probabilities](https://docs.typesafe.ai/primitives/noul),
[versioned models](https://docs.typesafe.ai/models).
