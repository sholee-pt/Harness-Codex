#!/usr/bin/env python3
"""Capture metadata from an opt-in ``codex exec --json`` process."""

from __future__ import annotations

import json
import inspect
import os
import platform
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import harness_eval_types as types


KNOWN_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}
COMMAND_ITEM_TYPES = {"command_execution"}
MCP_ITEM_TYPES = {"mcp_tool_call"}
WEB_ITEM_TYPES = {"web_search"}
FILE_ITEM_TYPES = {"file_change"}
SUBAGENT_ITEM_TYPES = {"subagent_call", "collab_agent_tool_call"}
KNOWN_ITEM_TYPES = {
    "agent_message",
    "reasoning",
    "plan",
    *COMMAND_ITEM_TYPES,
    *MCP_ITEM_TYPES,
    *WEB_ITEM_TYPES,
    *FILE_ITEM_TYPES,
    *SUBAGENT_ITEM_TYPES,
}


class CaptureError(types.EvaluationError):
    pass


def current_platform() -> str:
    value = platform.system().lower()
    return {"linux": "linux", "windows": "windows", "darwin": "macos"}.get(value, "unknown")


def unavailable_measurements() -> dict[str, dict[str, Any]]:
    return {
        "wallTimeMs": types.unavailable("milliseconds"),
        "processExitCode": types.unavailable("exit-code"),
        "inputTokens": types.unavailable("tokens"),
        "cachedInputTokens": types.unavailable("tokens"),
        "outputTokens": types.unavailable("tokens"),
        "reasoningOutputTokens": types.unavailable("tokens"),
        "commandExecutions": types.unavailable("count"),
        "mcpToolCalls": types.unavailable("count"),
        "webSearches": types.unavailable("count"),
        "fileChanges": types.unavailable("count"),
        "subagentRuns": types.unavailable("count"),
        "retryCount": types.unavailable("count"),
    }


def base_record(
    *,
    run_id: str,
    repository_id: str,
    task_instance_id: str,
    started_at: str,
    capture_mode: str,
    prompt_fingerprint: str | None,
    source_snapshot_id: str | None,
    manifest_sha256: str | None,
    topology_sha256: str | None,
    arm: str = "unpaired",
    category: str = "unknown",
    classification_source: str = "unknown",
    sandbox: str = "unknown",
    model_ref: str | None = None,
    reasoning_effort: str = "unknown",
    configured_execution_class: str = "unknown",
    configured_route_ref: str | None = None,
    configured_agent_refs: list[str] | None = None,
    configured_skill_refs: list[str] | None = None,
    quality_policy_refs: list[str] | None = None,
    comparison_id: str | None = None,
    pair_id: str | None = None,
    arm_order: str = "unpaired",
) -> dict[str, Any]:
    if capture_mode == "runtime-instrumented":
        scope = "codex-exec-jsonl"
        surface = "exec"
        ephemeral = True
        ignore_user_config = True
        ignore_rules = True
    elif capture_mode == "agent-reported":
        scope = "agent-report"
        surface = "interactive"
        ephemeral = False
        ignore_user_config = False
        ignore_rules = False
    else:
        scope = "user-input" if capture_mode == "manual" else "mixed"
        surface = "manual"
        ephemeral = False
        ignore_user_config = False
        ignore_rules = False
    empty_count = types.unavailable("count")
    record = {
        "schemaVersion": types.RUN_SCHEMA_VERSION,
        "runId": run_id,
        "recordState": "pending",
        "capture": {
            "captureMode": capture_mode,
            "captureScope": scope,
            "streamCompleteness": "unknown",
            "terminalEventObserved": False,
            "parserVersion": types.PARSER_VERSION,
            "parserCompatibility": "supported" if capture_mode == "runtime-instrumented" else "unsupported",
            "malformedEventCount": empty_count,
            "unknownEventCount": types.unavailable("count"),
            "rawEventsStored": False,
        },
        "timestamps": {"startedAt": started_at, "endedAt": None},
        "repository": {
            "repositoryId": repository_id,
            "sourceSnapshotId": source_snapshot_id,
            "manifestSha256": manifest_sha256,
            "topologySha256": topology_sha256,
        },
        "runtime": {
            "harnessVersion": types.HARNESS_VERSION,
            "codexVersion": None,
            "surface": surface,
            "modelRef": model_ref,
            "reasoningEffort": reasoning_effort,
            "platform": current_platform(),
            "sandbox": sandbox,
            "ephemeral": ephemeral,
            "ignoreUserConfig": ignore_user_config,
            "ignoreRules": ignore_rules,
        },
        "task": {
            "taskInstanceId": task_instance_id,
            "promptFingerprint": prompt_fingerprint,
            "category": category,
            "classificationSource": classification_source,
            "complexity": {"level": "unknown", "signals": ["unknown"]},
            "impact": {"level": "unknown", "signals": ["unknown"]},
            "uncertainty": {"level": "unknown", "signals": ["unknown"]},
        },
        "configuration": {
            "arm": arm,
            "configuredExecutionClass": configured_execution_class,
            "configuredRouteRef": configured_route_ref,
            "configuredAgentRefs": configured_agent_refs or [],
            "configuredSkillRefs": configured_skill_refs or [],
            "qualityPolicyRefs": quality_policy_refs or [],
            "observedExecution": {
                "executionClass": "unknown",
                "routeRef": None,
                "agentRefs": [],
                "skillRefs": [],
                "source": "unknown",
            },
        },
        "measurements": unavailable_measurements(),
        "outcome": {"completion": "unknown", "verification": [], "criticalFailure": False},
        "comparison": {
            "comparisonId": comparison_id,
            "pairId": pair_id,
            "armOrder": arm_order,
            "isolationStatus": "not-applicable" if pair_id is None else "partial",
            "isolationGaps": [],
        },
        "privacy": {
            "rawPromptStored": False,
            "rawTranscriptStored": False,
            "sourceContentStored": False,
            "absolutePathStored": False,
            "remoteUrlStored": False,
            "rawEventsStored": False,
        },
        "result": {
            "resultFingerprint": None,
            "verificationProfileFingerprint": None,
            "processCleanupVerified": True,
        },
        "integrity": {"recordSha256": None},
    }
    types.validate_run_record(types.seal_record(record))
    return record


@dataclass
class CaptureSummary:
    terminal_event_observed: bool
    completion: str
    usage: dict[str, int]
    counts: dict[str, int]
    malformed_count: int
    unknown_count: int
    parser_compatibility: str
    final_message: str | None


class JsonlAccumulator:
    def __init__(self, *, capture_final_message: bool = False):
        self.terminal_event_observed = False
        self.completion = "unknown"
        self.usage: dict[str, int] = {}
        self.counts = {"command": 0, "mcp": 0, "web": 0, "file": 0, "subagent": 0}
        self.malformed_count = 0
        self.unknown_count = 0
        self.capture_final_message = capture_final_message
        self.final_message: str | None = None

    def feed(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self.malformed_count += 1
            return
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self.malformed_count += 1
            return
        event_type = event["type"]
        if event_type not in KNOWN_EVENTS:
            self.unknown_count += 1
            return
        if event_type == "turn.completed":
            self.terminal_event_observed = True
            self.completion = "completed"
            usage = event.get("usage")
            if isinstance(usage, dict):
                for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                    value = usage.get(key)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        self.usage[key] = value
            return
        if event_type == "turn.failed":
            self.terminal_event_observed = True
            self.completion = "failed"
            return
        if event_type != "item.completed":
            return
        item = event.get("item")
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            self.unknown_count += 1
            return
        item_type = item["type"]
        if item_type in COMMAND_ITEM_TYPES:
            self.counts["command"] += 1
        elif item_type in MCP_ITEM_TYPES:
            self.counts["mcp"] += 1
        elif item_type in WEB_ITEM_TYPES:
            self.counts["web"] += 1
        elif item_type in FILE_ITEM_TYPES:
            self.counts["file"] += 1
        elif item_type in SUBAGENT_ITEM_TYPES:
            self.counts["subagent"] += 1
        elif item_type not in KNOWN_ITEM_TYPES:
            self.unknown_count += 1
        if self.capture_final_message and item_type == "agent_message" and isinstance(item.get("text"), str):
            self.final_message = item["text"]

    def summary(self) -> CaptureSummary:
        compatibility = "supported" if self.malformed_count == 0 and self.unknown_count == 0 else "degraded"
        return CaptureSummary(
            terminal_event_observed=self.terminal_event_observed,
            completion=self.completion,
            usage=dict(self.usage),
            counts=dict(self.counts),
            malformed_count=self.malformed_count,
            unknown_count=self.unknown_count,
            parser_compatibility=compatibility,
            final_message=self.final_message,
        )


def parse_jsonl(lines: Iterable[str], *, capture_final_message: bool = False) -> CaptureSummary:
    accumulator = JsonlAccumulator(capture_final_message=capture_final_message)
    for line in lines:
        accumulator.feed(line)
    return accumulator.summary()


def codex_preflight(
    codex_binary: str = "codex", *, environment: dict[str, str] | None = None
) -> str:
    try:
        version = subprocess.run(
            [codex_binary, "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=10,
            env=environment,
        ).stdout.strip()
        help_text = subprocess.run(
            [codex_binary, "exec", "--help"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=10,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise CaptureError(f"Codex CLI preflight failed: {type(exc).__name__}") from exc
    required = {"--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--sandbox", "--cd"}
    missing = sorted(flag for flag in required if flag not in help_text)
    if missing:
        raise CaptureError(f"Codex CLI is missing required flags: {', '.join(missing)}")
    return version


def _terminate_process_tree(process: subprocess.Popen[str], *, grace_seconds: float = 3.0) -> bool:
    if process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=grace_seconds)
        except (OSError, subprocess.TimeoutExpired):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=grace_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=grace_seconds)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        return False
    return process.poll() is not None


def windows_cleanup_implementation_sha256() -> str:
    """Identify the exact cleanup implementation covered by a local receipt."""
    return types.digest_bytes(inspect.getsource(_terminate_process_tree).encode("utf-8"))


def _isolated_environment(
    *, codex_home: Path | None, user_home: Path | None
) -> dict[str, str]:
    environment = os.environ.copy()
    if codex_home is not None:
        environment["CODEX_HOME"] = str(codex_home.resolve())
    if user_home is not None:
        home = user_home.resolve()
        home.mkdir(parents=True, exist_ok=True)
        environment["HOME"] = str(home)
        environment["USERPROFILE"] = str(home)
        environment["XDG_CONFIG_HOME"] = str(home / ".config")
        environment["XDG_DATA_HOME"] = str(home / ".local" / "share")
        environment["XDG_STATE_HOME"] = str(home / ".local" / "state")
        environment["XDG_CACHE_HOME"] = str(home / ".cache")
        if os.name == "nt":
            environment["APPDATA"] = str(home / "AppData" / "Roaming")
            environment["LOCALAPPDATA"] = str(home / "AppData" / "Local")
            drive, tail = os.path.splitdrive(str(home))
            if drive:
                environment["HOMEDRIVE"] = drive
                environment["HOMEPATH"] = tail
    return environment


def run_codex_jsonl(
    *,
    repository: Path,
    prompt: str,
    sandbox: str,
    timeout_seconds: float,
    codex_binary: str = "codex",
    codex_home: Path | None = None,
    user_home: Path | None = None,
    model: str | None = None,
    reasoning_effort: str = "unknown",
    capture_final_message: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[CaptureSummary, int | None, int, bool, str]:
    if sandbox not in {"read-only", "workspace-write"}:
        raise CaptureError("instrumented evaluator sandbox must be read-only or workspace-write")
    if reasoning_effort not in types.REASONING_EFFORTS:
        raise CaptureError("unsupported reasoning effort")
    if timeout_seconds <= 0:
        raise CaptureError("timeout must be positive")
    environment = _isolated_environment(codex_home=codex_home, user_home=user_home)
    version = codex_preflight(codex_binary, environment=environment)
    command = [
        codex_binary,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        sandbox,
        "--cd",
        str(repository.resolve()),
    ]
    if model:
        command.extend(["--model", model])
    if reasoning_effort != "unknown":
        command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
    if extra_args:
        command.extend(extra_args)
    command.append("-")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    if process.stdin is None or process.stdout is None:
        raise CaptureError("Codex process pipes were not created")
    event_queue: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                event_queue.put(line)
        finally:
            event_queue.put(None)

    reader = threading.Thread(target=read_stdout, name="harness-codex-jsonl", daemon=True)
    reader.start()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except OSError:
        try:
            process.stdin.close()
        except OSError:
            pass
    accumulator = JsonlAccumulator(capture_final_message=capture_final_message)
    deadline = started + timeout_seconds
    timed_out = False
    stream_closed = False
    while not stream_closed:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            item = event_queue.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if process.poll() is not None and not reader.is_alive():
                break
            continue
        if item is None:
            stream_closed = True
        else:
            accumulator.feed(item)
    cleanup_verified = True
    if timed_out:
        cleanup_verified = _terminate_process_tree(process)
    else:
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup_verified = _terminate_process_tree(process)
    reader.join(timeout=1.0)
    elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
    summary = accumulator.summary()
    if timed_out:
        summary.completion = "interrupted"
    return summary, process.returncode, elapsed_ms, cleanup_verified, version


def apply_capture_to_record(
    record: dict[str, Any],
    *,
    summary: CaptureSummary,
    exit_code: int | None,
    elapsed_ms: int,
    cleanup_verified: bool,
    codex_version: str,
    ended_at: str,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(record))
    compatibility = summary.parser_compatibility
    stream_complete = summary.terminal_event_observed and compatibility == "supported" and cleanup_verified
    updated["capture"].update(
        {
            "streamCompleteness": "complete" if stream_complete else "partial",
            "terminalEventObserved": summary.terminal_event_observed,
            "parserCompatibility": compatibility,
            "malformedEventCount": types.measurement(
                summary.malformed_count,
                unit="count",
                state="measured",
                source="codex-jsonl",
                fidelity="exact",
                completeness="complete",
            ),
            "unknownEventCount": types.measurement(
                summary.unknown_count,
                unit="count",
                state="measured",
                source="codex-jsonl",
                fidelity="exact",
                completeness="complete",
            ),
        }
    )
    metric_completeness = "complete" if stream_complete else "partial"
    updated["measurements"]["wallTimeMs"] = types.measurement(
        elapsed_ms,
        unit="milliseconds",
        state="measured",
        source="evaluator-clock",
        fidelity="exact",
        completeness="complete",
    )
    if exit_code is not None:
        updated["measurements"]["processExitCode"] = types.measurement(
            exit_code,
            unit="exit-code",
            state="measured",
            source="process-exit",
            fidelity="exact",
            completeness="complete",
        )
    usage_map = {
        "inputTokens": "input_tokens",
        "cachedInputTokens": "cached_input_tokens",
        "outputTokens": "output_tokens",
        "reasoningOutputTokens": "reasoning_output_tokens",
    }
    for target, source in usage_map.items():
        if source in summary.usage:
            updated["measurements"][target] = types.measurement(
                summary.usage[source],
                unit="tokens",
                state="measured",
                source="codex-jsonl",
                fidelity="exact",
                completeness=metric_completeness,
            )
    count_map = {
        "commandExecutions": "command",
        "mcpToolCalls": "mcp",
        "webSearches": "web",
        "fileChanges": "file",
        "subagentRuns": "subagent",
    }
    for target, source in count_map.items():
        updated["measurements"][target] = types.measurement(
            summary.counts[source],
            unit="count",
            state="measured",
            source="codex-jsonl",
            fidelity="exact",
            completeness=metric_completeness,
        )
    completion = summary.completion
    if exit_code not in {None, 0}:
        completion = "failed"
    updated["outcome"]["completion"] = completion
    updated["outcome"]["criticalFailure"] = completion in {"failed", "interrupted"}
    updated["timestamps"]["endedAt"] = ended_at
    updated["runtime"]["codexVersion"] = codex_version or None
    updated["result"]["processCleanupVerified"] = cleanup_verified
    updated["recordState"] = "completed"
    return updated
