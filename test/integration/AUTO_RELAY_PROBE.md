# Auto relay feasibility experiment

Run the **Auto relay feasibility** workflow manually on Linux. It downloads the
official Codex package identified by `build/native_ui/upstream.json` and the
latest official stable release at run time. It does not compile Codex, publish a
release, change the production integration, or cancel another workflow.

The real terminal UI runs in a pseudo-terminal and connects through a local
WebSocket relay to the real official app-server. The relay adds a distinct
`codex-auto-harness` catalog entry with the display name `Auto`; it never replaces
an official model identifier. Selected Auto turns use the existing Harness
router, and only model/effort settings are changed in forwarded turn requests.
All other protocol messages pass through. Each process uses a temporary
`CODEX_HOME`, a synthetic project, read-only sandbox settings and a local fixture
Responses provider. No account credentials or paid model calls are used.

The evidence artifact records official archive digests, executable hashes before
and after execution, real terminal text/ANSI captures, routing decisions and the
model/effort received by the fixture provider. It also records whether choosing
the virtual model writes that identifier into the isolated default config.
Those writes must not be carried into a production integration without review.

`menuRoutingFooterSatisfied` requires the exact Auto label as the first entry, delivery of each
selected model/effort, and matching Auto/model/effort display in the last six
terminal rows. The captures remain the primary evidence for assessing rendering;
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
