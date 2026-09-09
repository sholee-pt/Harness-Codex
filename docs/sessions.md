# Project and conversation lifecycle

One project has one canonical harness: `.codex/agents/`, `.agents/skills/`, its managed instructions and `.harness/manifest.json`. All conversations share it. Project configuration is independent of Git repository layout.

```text
init → canonical project harness ← config / reset
                  │
          ┌───────┼────────┐
         new A   new B   resume C
```

`init` installs the generator and asks native Codex to configure the project. A repeated `init` reports an existing harness; a brief or `--install-only` explicitly requests the corresponding update step. `config` reviews the existing configuration. `new` and `resume` only validate and launch; they create no project manifests, agent copies or session snapshots.

```bash
harness-codex new "Implement the requested change"
harness-codex resume
harness-codex resume --last
harness-codex resume SESSION_ID
```

The native resume picker and current-directory `--last` selection remain Codex responsibilities. The wrapper supplies the selected project as `--cd` and a current-harness activation prompt. It does not select models, override permissions, replace hooks or implement its own conversation database. These behaviors follow [Codex CLI resume documentation](https://learn.chatgpt.com/docs/developer-commands?surface=cli) and the [native CLI argument handling](https://github.com/openai/codex/blob/main/codex-rs/cli/src/main.rs).

If a conversation was created with H1 and the project now has H2, resume preserves its history and tells Codex to re-read H2. Historical model context is not erased. Re-reading is an instruction to Codex, not proof that every model decision obeys it. Concurrent launches do not mutate the manifest; concurrent project edits still require normal coordination.

## Configuration progress

`init`, `config` and an applied `reset` use the [native Codex App Server](https://learn.chatgpt.com/docs/app-server) over local standard input/output. The configuration prompt and protocol JSON stay out of the terminal. The screen shows observed phases, elapsed seconds, the native session ID and the final Codex message. This is an indeterminate timer, not a predicted completion percentage.

The bridge supplies the project directory and task text. It does not override the model, sandbox, approval policy or trusted hooks. Command/network approvals display the request, file approvals include the received diff, and only typing exactly `yes` accepts that request. Unfamiliar permission-profile or tool requests are declined/stopped with instructions to use `--interactive`; they are never silently granted. A terminal is required for questions and approvals. The protocol is checked against Codex CLI 0.153.4; older versions can use the native UI fallback.

```bash
harness-codex init --goal-file PROJECT.md
harness-codex config --timeout 3600
# Resume an incomplete configuration or answer a final Codex question:
harness-codex config --resume SESSION_ID --goal "The project's purpose is ..."
# Use the original native conversation screen when needed:
harness-codex config --interactive
```

The default time limit is 1,800 seconds. Ctrl+C, connection failure and timeout stop the child connection and preserve project files for inspection. Incomplete generation is not declared configured; run `status` and continue `config`. Harness keeps no transport transcript or session registry in the project. Native Codex retains its own history according to its settings. This presentation does not hide prompts from native history or prove generation quality.

`new` and `resume` remain interactive Codex conversations, including the visible harness activation message. A task conversation is distinct from the configuration progress session.

Diagnostics use readable summaries by default. `status --json` and `doctor --json` return full JSON; previews and update commands also accept `--json` for their report while retaining command guidance. The deterministic helper scripts keep their existing JSON contracts.

## Revision and optional session metadata

Launches print `sha256:<digest>`, calculated from the canonical, key-sorted manifest JSON after validation. The manifest binds managed file hashes and project evidence. Formatting-only manifest changes do not alter the revision. Unmanaged files and any future `.harness/sessions/` records do not enter the fingerprint.

This release deliberately defers automatic session registry creation. Native [SessionStart hooks](https://learn.chatgpt.com/docs/hooks) provide a stable session ID, but the interactive process does not return that ID to this wrapper. Installing or replacing trusted user hooks is not implicit in starting a conversation. No IDs are invented, transcripts scraped or project harnesses copied. Consequently the original H1 revision is not automatically persisted per conversation in this release.

`start` is a compatibility alias with a deprecation warning. `configure` remains an alias for `config`.
