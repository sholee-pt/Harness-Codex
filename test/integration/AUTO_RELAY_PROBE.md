# Auto relay feasibility experiment

Run the **Auto relay feasibility** workflow manually on Linux. It downloads the
official Codex package identified by `build/native_ui/upstream.json` and the
latest official stable release at run time. It does not compile Codex, publish a
release, change the production integration, or cancel another workflow.

The real terminal UI runs in a pseudo-terminal and connects through a local
WebSocket relay to the real official app-server. The relay adds a distinct
`codex-auto-harness` catalog entry with the display name `Auto`; it never replaces
an official model identifier. Selected Auto turns use the existing Harness
router with thread-local Auto state. Successful explicit model-setting requests
enable or disable Auto for that thread; a routed model echoed by the server does
not itself disable Auto. Auto config writes preserve the real default model read
from the server, so the virtual identifier does not become the default for an
unrelated session. Other configuration edits and permission settings pass through.
This relay state is temporary; it does not yet establish resume compatibility.
Each process uses a temporary
`CODEX_HOME`, a synthetic project, read-only sandbox settings and a local fixture
Responses provider. No account credentials or paid model calls are used.

The evidence artifact records official archive digests, executable hashes before
and after execution, real terminal text/ANSI captures, routing decisions and the
model/effort received by the fixture provider. It also records whether choosing
the virtual model writes that identifier into the isolated default config and
which model writes the relay replaced. The upstream terminal and server remain
unmodified, including their model labels and settings notifications.

The startup driver dismisses only the recognized new-model announcement by
choosing `Use existing model`. It never answers permission or login dialogs.
Requests are correlated by the main thread ID, returned turn ID and input digest;
background helper threads cannot satisfy a foreground-turn check. The provider
records the `thread-id` and `session-id` headers and the final user-input digest,
not an assumed request ordering. Missing correlation fails the experiment.

`menuRoutingFooterSatisfied` requires the exact Auto label as the first entry, delivery of each
selected model/effort on two completed turns with distinct selections, continued
Auto state, and matching Auto/model/effort display below the last input prompt.
Trailing blank rows and historical model-change messages are excluded from the
footer check. The captures remain the primary evidence for assessing rendering;
the text checks alone do not prove pixel-identical appearance. A passing Actions
job means that the experiment ran, not that the proposed design satisfies the
requested UX. An unmet UX condition is recorded as false; execution or setup
errors fail the job and preserve available evidence.

This is one minimal relay design, not an exhaustive proof that all relay designs
are possible or impossible. Resume, real account restrictions, permission dialogs,
live model inference, future Codex versions and production reliability remain
unverified by this first-stage experiment. Inspect the artifact after the run;
do not infer those properties from a green workflow result.

Dependencies in `requirements-auto-relay.txt` are installed only for this manual
experiment, not into the shipped Harness package. The workflow has one Ubuntu
job, read-only repository permissions, a 15-minute limit and seven-day evidence
retention. Its logs and artifact contain synthetic test data only.
