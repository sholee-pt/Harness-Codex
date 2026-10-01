"""Backward-compatible generated advice for shared projects and host changes."""

GUIDANCE = """## Workspace portability

Resolve project-internal files from the current selected workspace, using relative paths in persistent instructions and commands. Do not retain an installation-time mount prefix or interpreter path as a project invariant. After changing hosts or resuming a relocated project, read `harness-codex context --project CURRENT_ROOT` once if available; it reports only the current host's bounded sandbox observation. Use `context --resolve OLD_PATH --project CURRENT_ROOT` for a recorded old project prefix. Verify the resulting source before editing; never rewrite arbitrary user code, native conversation history or external paths by substring replacement. External resources require an explicitly selected location on the current host.

An unavailable sandbox observation applies only to that host and probe, not all servers or permissions. Avoid repeating an identical known sandbox failure: use an allowed native approval route or report the host setup requirement. Never automatically disable sandboxing or broaden permissions. An unknown or stale observation proves nothing; after environment repair use `harness-codex context --refresh`. Pass the relevant host/path constraint to delegated agents without running a new probe for each agent or turn.

When a task needs explicitly authorized external code and Graft is enabled, attach only that file or narrow directory with `harness-codex graft add PATH --name LABEL --project CURRENT_ROOT`. Use `graft status` to reuse a binding and `graft remove LABEL` when it is no longer needed. Never scan project ancestors automatically. External results are navigation hints, not ownership or permission; unsupported files remain ordinary source reads."""


AGENT_GUIDANCE = """## Workspace portability

Use the current workspace root and project-relative paths, not old mount/interpreter paths from history. Inherit the parent's current-host sandbox observation; do not repeat a known identical sandbox failure. Use only an allowed native approval route or report the host issue, never silently broaden permissions. Verify explicitly selected external sources at their current locations."""


def append_guidance(content, *, agent=False):
    guidance = AGENT_GUIDANCE if agent else GUIDANCE
    if guidance in content.replace('\r\n', '\n'):
        return content
    return content.rstrip() + '\n\n' + guidance + '\n'
