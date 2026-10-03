#!/usr/bin/env python3
"""Opt-in local evaluation and observability CLI for Harness for Codex."""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import harness_eval_capture as capture
import harness_eval_compare as compare
import harness_eval_propose as propose
import harness_eval_store as store_module
import harness_eval_types as types
import harness_eval_schema2 as schema2
import harness_eval_view as evaluation_view
import harness_usage
import harness_metadata
import harness_patch_scope
import harness_state
import harness_change_discipline
import harness_topology
import harness_workspace
import validate_harness


def _print(value: Any) -> None:
    print(types.canonical_text(value), end="")


def _store(args: argparse.Namespace) -> store_module.EvaluationStore:
    state_home = Path(args.state_home) if getattr(args, "state_home", None) else None
    return store_module.EvaluationStore(state_home)


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root.resolve()), *arguments],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _snapshot(root: Path) -> str | None:
    try:
        return f"git:{_git(root, 'rev-parse', 'HEAD').stdout.strip()}"
    except (OSError, subprocess.CalledProcessError):
        return None


def _manifest_metadata(root: Path) -> tuple[str | None, str | None]:
    path = root / ".harness" / "manifest.json"
    if not path.is_file():
        return None, None
    data = path.read_bytes()
    manifest_hash = types.digest_bytes(data)
    try:
        manifest = json.loads(data)
        topology_hash = types.digest_bytes(types.canonical_bytes(manifest.get("topology")))
    except (UnicodeError, json.JSONDecodeError):
        topology_hash = None
    return manifest_hash, topology_hash


def _measured_value(value: Any, *, source: str = "run-configuration-snapshot") -> dict[str, Any]:
    return schema2.value_observation(
        value,
        state="measured",
        source=source,
        fidelity="exact",
        completeness="complete",
    )


def _measured_refs(refs: list[str], *, source: str = "run-configuration-snapshot") -> dict[str, Any]:
    return schema2.reference_set(
        sorted(refs),
        state="measured",
        source=source,
        fidelity="exact",
        completeness="complete",
    )


def _configuration_snapshot(
    evaluation_store: store_module.EvaluationStore,
    repository_id: str,
    root: Path,
    args: argparse.Namespace,
    arm: str,
) -> dict[str, Any]:
    manifest_path = root / ".harness" / "manifest.json"
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest = None

    if manifest is None and manifest_path.exists():
        declared = {
            "executionClass": schema2.unavailable_value(),
            "route": schema2.unavailable_references(),
            "agents": schema2.unavailable_references(),
            "skills": schema2.unavailable_references(),
            "qualityPolicies": schema2.unavailable_references(),
            "independentReview": schema2.unavailable_value(),
            "changeDisciplineVersion": schema2.unavailable_value(),
            "projectHarnessFingerprint": schema2.unavailable_value(),
            "bundleFingerprint": schema2.unavailable_value(),
        }
    else:
        topology = manifest.get("topology", {}) if manifest else {}
        if not isinstance(topology, dict):
            topology = {}

        def names(key: str, field: str = "name") -> list[str]:
            values = topology.get(key, [])
            if not isinstance(values, list):
                return []
            return [item[field] for item in values if isinstance(item, dict) and isinstance(item.get(field), str)]

        agent_refs = [evaluation_store.pseudonym(repository_id, "agent", name) for name in names("agents")]
        skill_refs = [evaluation_store.pseudonym(repository_id, "skill", name) for name in names("skills")]
        route_refs = [evaluation_store.pseudonym(repository_id, "route", name) for name in names("routingPolicies", "id")]
        policy_refs = [evaluation_store.pseudonym(repository_id, "quality-policy", name) for name in names("qualityPatternPolicies", "id")]
        collaboration_patterns = topology.get("collaborationPatterns", [])
        quality_policies = topology.get("qualityPatternPolicies", [])
        independent_review = (
            isinstance(collaboration_patterns, list)
            and "producer-reviewer" in collaboration_patterns
        ) or (
            isinstance(quality_policies, list)
            and any(
                isinstance(policy, dict)
                and policy.get("name") == "independent-safety-review"
                for policy in quality_policies
            )
        )
        project_harness = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
        if project_harness.is_file():
            project_fingerprint = _measured_value(evaluation_store.fingerprint(project_harness.read_bytes()))
            try:
                skill_text = project_harness.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                discipline = schema2.unavailable_value()
            else:
                discipline = (
                    _measured_value(harness_change_discipline.CHANGE_DISCIPLINE_VERSION)
                    if harness_change_discipline.PROJECT_BLOCK in harness_change_discipline.normalize_line_endings(skill_text)
                    else schema2.unavailable_value()
                )
        else:
            project_fingerprint = schema2.value_observation(
                None, state="not-applicable", source="none", fidelity="unknown", completeness="not-applicable"
            )
            discipline = schema2.value_observation(
                None, state="not-applicable", source="none", fidelity="unknown", completeness="not-applicable"
            )
        bundle_material = {
            "agents": sorted(agent_refs),
            "skills": sorted(skill_refs),
            "routes": sorted(route_refs),
            "qualityPolicies": sorted(policy_refs),
            "independentReview": independent_review,
            "changeDisciplineVersion": discipline.get("value"),
            "projectHarnessFingerprint": project_fingerprint.get("value"),
        }
        declared = {
            "executionClass": schema2.unavailable_value(),
            "route": _measured_refs(route_refs),
            "agents": _measured_refs(agent_refs),
            "skills": _measured_refs(skill_refs),
            "qualityPolicies": _measured_refs(policy_refs),
            "independentReview": _measured_value(independent_review),
            "changeDisciplineVersion": discipline,
            "projectHarnessFingerprint": project_fingerprint,
            "bundleFingerprint": _measured_value(
                evaluation_store.fingerprint(types.canonical_bytes(bundle_material))
            ),
        }

    execution_class = getattr(args, "execution_class", "unknown")
    if execution_class == "unknown":
        expected = {
            "executionClass": schema2.unavailable_value(),
            "route": schema2.unavailable_references(),
            "agents": schema2.unavailable_references(),
            "skills": schema2.unavailable_references(),
            "independentReview": schema2.unavailable_value(),
        }
    else:
        expected = {
            "executionClass": _measured_value(execution_class, source="comparison-plan"),
            "route": _measured_refs([], source="comparison-plan") if execution_class == "direct" else schema2.unavailable_references(),
            "agents": _measured_refs([], source="comparison-plan") if execution_class == "direct" else schema2.unavailable_references(),
            "skills": _measured_refs([], source="comparison-plan") if execution_class == "direct" else schema2.unavailable_references(),
            "independentReview": _measured_value(False, source="comparison-plan") if execution_class == "direct" else schema2.unavailable_value(),
        }
    return {
        "arm": arm,
        "declaredConfiguration": declared,
        "expectedExecution": expected,
        "discoveredConfiguration": {
            "agents": schema2.unavailable_references(),
            "skills": schema2.unavailable_references(),
        },
        "observedExecution": {
            "executionClass": schema2.unavailable_value(),
            "route": schema2.unavailable_references(),
            "agents": schema2.unavailable_references(),
            "skills": schema2.unavailable_references(),
            "independentReview": schema2.unavailable_value(),
        },
    }


RESULT_FINGERPRINT_MAX_FILES = 4096
RESULT_FINGERPRINT_MAX_BYTES = 64 * 1024 * 1024
VERIFICATION_QUIESCENCE_SECONDS = 0.2
PAIRED_MATERIALIZATION_MODE = "independent-local-clone-overlay"
PAIRED_OVERLAY_MAX_FILES = 4096
PAIRED_OVERLAY_MAX_BYTES = 64 * 1024 * 1024
PROJECT_CONFIG_LOAD_GAP = "project-config-load-unverified"
PROJECT_AGENT_LOAD_GAP = "project-agent-load-unverified"
PROJECT_CONTEXT_GAP = "user-project-context-unavailable"


def _length_prefixed(payload: bytearray, value: bytes) -> None:
    payload.extend(len(value).to_bytes(8, "big"))
    payload.extend(value)


def _collect_result_fingerprint_payload(
    root: Path,
    *,
    base_ref: str = "HEAD",
) -> bytes:
    """Collect one bounded snapshot of tracked and non-ignored untracked content."""
    command = ["git", "-C", str(root.resolve())]
    base_tree = subprocess.run(
        [*command, "rev-parse", f"{base_ref}^{{tree}}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.strip()
    diff = subprocess.run(
        [*command, "diff", base_ref, "--binary", "--no-ext-diff"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    raw_names = subprocess.run(
        [*command, "ls-files", "--others", "--exclude-standard", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    names = [name for name in raw_names.split(b"\0") if name]
    if len(names) > RESULT_FINGERPRINT_MAX_FILES:
        raise types.EvaluationError("untracked file count exceeds the fingerprint bound")
    if len(diff) > RESULT_FINGERPRINT_MAX_BYTES:
        raise types.EvaluationError("tracked diff exceeds the fingerprint byte bound")
    payload = bytearray(b"harness-result-fingerprint-v3\0")
    _length_prefixed(payload, base_tree)
    _length_prefixed(payload, diff)
    consumed = len(diff)
    for raw_name in names:
        path = root / os.fsdecode(raw_name)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            kind = b"l"
            content = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"f"
            if metadata.st_size > RESULT_FINGERPRINT_MAX_BYTES - consumed:
                raise types.EvaluationError("untracked content exceeds the fingerprint byte bound")
            content = path.read_bytes()
            final_metadata = path.lstat()
            if (
                len(content) != metadata.st_size
                or final_metadata.st_size != metadata.st_size
                or final_metadata.st_mtime_ns != metadata.st_mtime_ns
            ):
                raise types.EvaluationError("untracked file changed during fingerprinting")
        else:
            raise types.EvaluationError("unsupported untracked artifact kind")
        consumed += len(content)
        if consumed > RESULT_FINGERPRINT_MAX_BYTES:
            raise types.EvaluationError("result content exceeds the fingerprint byte bound")
        _length_prefixed(payload, raw_name)
        payload.extend(kind)
        _length_prefixed(payload, types.digest_bytes(content).encode("ascii"))
    return bytes(payload)


def _stable_payload(
    collector: Any,
    *,
    changed_message: str,
) -> bytes:
    first_sha256 = types.digest_bytes(collector())
    second = collector()
    if first_sha256 != types.digest_bytes(second):
        raise types.EvaluationError(changed_message)
    return second


def _result_fingerprint(
    store: store_module.EvaluationStore,
    root: Path,
    *,
    base_ref: str = "HEAD",
) -> str | None:
    """HMAC two identical complete snapshots of the task result content."""
    try:
        payload = _stable_payload(
            lambda: _collect_result_fingerprint_payload(root, base_ref=base_ref),
            changed_message="repository changed during fingerprinting",
        )
        return store.fingerprint(payload)
    except (OSError, subprocess.CalledProcessError, types.EvaluationError) as exc:
        print(f"warning: result fingerprint unavailable: {exc}", file=sys.stderr)
        return None


def _collect_repository_state_payload(root: Path, *, base_ref: str) -> bytes:
    """Collect content plus HEAD, symbolic HEAD, index, and porcelain status."""
    command = ["git", "-C", str(root.resolve())]
    head = subprocess.run(
        [*command, "rev-parse", "--verify", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.strip()
    symbolic_process = subprocess.run(
        [*command, "symbolic-ref", "--quiet", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if symbolic_process.returncode not in {0, 1}:
        raise types.EvaluationError("could not inspect symbolic HEAD")
    symbolic_head = symbolic_process.stdout.strip() if symbolic_process.returncode == 0 else b"DETACHED"
    index_entries = subprocess.run(
        [*command, "ls-files", "--stage", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    status = subprocess.run(
        [*command, "status", "--porcelain=v2", "-z", "--untracked-files=all"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    content = _collect_result_fingerprint_payload(root, base_ref=base_ref)
    payload = bytearray(b"harness-repository-state-v1\0")
    for value in (head, symbolic_head, index_entries, status, content):
        _length_prefixed(payload, value)
    return bytes(payload)


def _repository_state_signature(
    store: store_module.EvaluationStore,
    root: Path,
    *,
    base_ref: str,
) -> str | None:
    """HMAC two identical complete Git repository-state snapshots."""
    try:
        payload = _stable_payload(
            lambda: _collect_repository_state_payload(root, base_ref=base_ref),
            changed_message="repository state changed during signature measurement",
        )
        return store.fingerprint(payload)
    except (OSError, subprocess.CalledProcessError, types.EvaluationError) as exc:
        print(f"warning: repository state signature unavailable: {exc}", file=sys.stderr)
        return None


def _new_record(
    *,
    evaluation_store: store_module.EvaluationStore,
    root: Path,
    repository_id: str,
    prompt: bytes | None,
    capture_mode: str,
    args: argparse.Namespace,
    arm: str = "unpaired",
    comparison_id: str | None = None,
    pair_id: str | None = None,
    arm_order: str = "unpaired",
    source_snapshot_id_override: str | None = None,
) -> dict[str, Any]:
    manifest_hash, topology_hash = _manifest_metadata(root)
    model = getattr(args, "model", None)
    model_ref = evaluation_store.pseudonym(repository_id, "model", model) if model else None
    selected_arm = arm
    return capture.base_record(
        run_id=str(evaluation_store.ids.new_uuid()),
        repository_id=repository_id,
        task_instance_id=str(evaluation_store.ids.new_uuid()),
        started_at=types.timestamp_text(evaluation_store.clock.now_utc()),
        capture_mode=capture_mode,
        prompt_fingerprint=evaluation_store.fingerprint(prompt) if prompt is not None else None,
        source_snapshot_id=(
            source_snapshot_id_override
            if source_snapshot_id_override is not None
            else _snapshot(root)
        ),
        manifest_sha256=manifest_hash,
        topology_sha256=topology_hash,
        arm=selected_arm,
        category=getattr(args, "category", "unknown"),
        classification_source=getattr(args, "classification_source", "unknown"),
        sandbox=getattr(args, "sandbox", "unknown"),
        model_ref=model_ref,
        reasoning_effort=getattr(args, "reasoning_effort", "unknown"),
        configured_execution_class=getattr(args, "execution_class", "unknown"),
        comparison_id=comparison_id,
        pair_id=pair_id,
        arm_order=arm_order,
        configuration=_configuration_snapshot(
            evaluation_store, repository_id, root, args, selected_arm
        ),
    )


def _set_result_fingerprint(record: dict[str, Any], fingerprint: str | None) -> None:
    record["result"]["resultFingerprint"] = (
        schema2.value_observation(
            fingerprint,
            state="measured",
            source="git-evaluator",
            fidelity="exact",
            completeness="complete",
        )
        if fingerprint is not None
        else schema2.unavailable_value()
    )


def _prompt_bytes(args: argparse.Namespace) -> bytes:
    if getattr(args, "task_file", None):
        return Path(args.task_file).read_bytes()
    if getattr(args, "task_stdin", False):
        return sys.stdin.buffer.read()
    raise types.EvaluationError("provide --task-file or --task-stdin")


def command_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    prompt_bytes = _prompt_bytes(args)
    prompt = prompt_bytes.decode("utf-8")
    evaluation_store = _store(args)
    repository_id = evaluation_store.register_repository(root)
    record = _new_record(
        evaluation_store=evaluation_store,
        root=root,
        repository_id=repository_id,
        prompt=prompt_bytes,
        capture_mode="runtime-instrumented",
        args=args,
        arm=args.arm,
    )
    evaluation_store.create_pending(record)
    summary, exit_code, elapsed_ms, cleanup_verified, version = capture.run_codex_jsonl(
        repository=root,
        prompt=prompt,
        sandbox=args.sandbox,
        timeout_seconds=args.timeout,
        codex_binary=args.codex_binary,
        codex_home=Path(args.codex_home) if args.codex_home else None,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    completed = capture.apply_capture_to_record(
        record,
        summary=summary,
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        cleanup_verified=cleanup_verified,
        codex_version=version,
        ended_at=types.timestamp_text(evaluation_store.clock.now_utc()),
    )
    _set_result_fingerprint(completed, _result_fingerprint(evaluation_store, root))
    if args.patch_scope_profile:
        patch_profile = harness_patch_scope.validate_profile(
            types.load_json(Path(args.patch_scope_profile))
        )
        completed["result"]["patchScope"] = harness_patch_scope.evaluate(
            root=root,
            profile=patch_profile,
            repository_id=repository_id,
            store=evaluation_store,
        )
    evaluation_store.complete_run(completed)
    _print({"repositoryId": repository_id, "runId": completed["runId"], "completion": completed["outcome"]["completion"]})
    return 0 if completed["outcome"]["completion"] == "completed" else 1


def command_record_start(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    evaluation_store = _store(args)
    repository_id = evaluation_store.register_repository(root)
    record = _new_record(
        evaluation_store=evaluation_store,
        root=root,
        repository_id=repository_id,
        prompt=None,
        capture_mode=args.capture,
        args=args,
    )
    evaluation_store.create_pending(record)
    _print({"repositoryId": repository_id, "runId": record["runId"], "recordState": "pending"})
    return 0


def command_record_complete(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    repository_id, record = evaluation_store.find_run(args.run)
    if record["recordState"] != "pending":
        raise store_module.StoreError("completed records are immutable")
    completed = copy.deepcopy(record)
    completed["recordState"] = "completed"
    completed["timestamps"]["endedAt"] = types.timestamp_text(evaluation_store.clock.now_utc())
    completed["outcome"]["completion"] = args.completion
    completed["outcome"]["criticalFailure"] = args.completion in {"failed", "interrupted"}
    pending_observation = None
    if args.report:
        pending_observation = _observation_from_report(
            evaluation_store=evaluation_store,
            repository_id=repository_id,
            run=completed,
            report_path=Path(args.report),
            kind="supplement",
            supersedes=None,
        )
    evaluation_store.complete_run(completed)
    observation_id = None
    if pending_observation is not None:
        observation_id = evaluation_store.add_observation(repository_id, pending_observation).stem
    _print({
        "repositoryId": repository_id,
        "runId": args.run,
        "recordState": "completed",
        "observationId": observation_id,
    })
    return 0


def command_annotate(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    repository_id, _ = evaluation_store.find_run(args.run)
    correction = (
        types.unavailable("count")
        if args.corrections is None
        else types.measurement(
            args.corrections,
            unit="count",
            state="measured",
            source="user-annotation",
            fidelity="reported",
            completeness="complete",
        )
    )
    annotation = {
        "schemaVersion": types.ANNOTATION_SCHEMA_VERSION,
        "annotationId": str(evaluation_store.ids.new_uuid()),
        "repositoryId": repository_id,
        "runId": args.run,
        "createdAt": types.timestamp_text(evaluation_store.clock.now_utc()),
        "supersedesAnnotationId": args.supersedes,
        "source": "user",
        "acceptance": args.acceptance,
        "correctionCount": correction,
        "reopened": args.reopened,
        "freeTextStored": False,
        "integrity": {"recordSha256": None},
    }
    path = evaluation_store.add_annotation(repository_id, annotation)
    _print({"repositoryId": repository_id, "runId": args.run, "annotationId": path.stem})
    return 0


def _observation_from_report(
    *,
    evaluation_store: store_module.EvaluationStore,
    repository_id: str,
    run: dict[str, Any],
    report_path: Path | None,
    kind: str,
    supersedes: str | None,
) -> dict[str, Any]:
    if run["schemaVersion"] != 2:
        raise types.EvaluationError("structured observations require a Schema 2 run")
    if kind == "withdrawal":
        if report_path is not None:
            raise types.EvaluationError("withdrawal forbids a report payload")
        if supersedes is None:
            raise types.EvaluationError("withdrawal requires --supersedes")
        payload = None
        provenance = {"source": "user-report", "fidelity": "reported", "completeness": "not-applicable"}
    else:
        if report_path is None:
            raise types.EvaluationError(f"{kind} requires --report")
        if kind == "supplement" and supersedes is not None:
            raise types.EvaluationError("supplement cannot use --supersedes")
        if kind == "replacement" and supersedes is None:
            raise types.EvaluationError("replacement requires --supersedes")
        report = types.load_json(report_path)
        types.validate_manual_report(report)
        source = "user-report" if report["captureMode"] == "user-reported" else "agent-report"
        observed = report["observedExecution"]
        completeness = observed["completeness"]

        def reported_value(value: Any) -> dict[str, Any]:
            return (
                schema2.value_observation(
                    value,
                    state="measured",
                    source=source,
                    fidelity="reported",
                    completeness="partial" if completeness == "unknown" else completeness,
                )
                if value is not None
                else schema2.unavailable_value()
            )

        def component_refs(logical_ids: list[str] | None, component_kind: str, declared_key: str) -> dict[str, Any]:
            if logical_ids is None:
                return schema2.unavailable_references()
            if not logical_ids:
                return schema2.reference_set(
                    [],
                    state="measured",
                    source=source,
                    fidelity="reported",
                    completeness="partial" if completeness == "unknown" else completeness,
                )
            declared = run["configuration"]["declaredConfiguration"][declared_key]
            if declared["state"] != "measured":
                raise types.EvaluationError("run-declared-configuration-unavailable")
            refs = [evaluation_store.pseudonym(repository_id, component_kind, logical_id) for logical_id in logical_ids]
            if not set(refs) <= set(declared["refs"]):
                raise types.EvaluationError("invalid-component-id")
            return schema2.reference_set(
                refs,
                state="measured",
                source=source,
                fidelity="reported",
                completeness="partial" if completeness == "unknown" else completeness,
            )

        route_ids = [observed["routeRef"]] if observed["routeRef"] is not None else []
        execution = {
            "executionClass": reported_value(observed["executionClass"]),
            "route": component_refs(route_ids, "route", "route"),
            "agents": component_refs(observed["agentRefs"], "agent", "agents"),
            "skills": component_refs(observed["skillRefs"], "skill", "skills"),
            "independentReview": reported_value(observed["independentReview"]),
        }
        verification = [
            {
                "checkRef": evaluation_store.pseudonym(repository_id, "check", check["id"]),
                "kind": check["kind"],
                "result": check["result"],
                "exitCode": check["exitCode"],
            }
            for check in report["verification"]
        ]
        payload = {
            "observedExecution": execution,
            "measurements": report["measurements"],
            "verification": verification,
        }
        provenance = {"source": source, "fidelity": "reported", "completeness": completeness}
    observation = {
        "schemaVersion": types.OBSERVATION_SCHEMA_VERSION,
        "observationId": str(evaluation_store.ids.new_uuid()),
        "repositoryId": repository_id,
        "runId": run["runId"],
        "createdAt": types.timestamp_text(evaluation_store.clock.now_utc()),
        "lifecycle": {"kind": kind, "supersedesObservationId": supersedes},
        "provenance": provenance,
        "privacy": {
            "rawReportStored": False,
            "freeTextStored": False,
            "rawComponentNamesStored": False,
        },
        "integrity": {"recordSha256": None},
    }
    if payload is not None:
        observation["payload"] = payload
    sealed = types.seal_record(observation)
    types.validate_observation_record(sealed)
    return sealed


def command_add_observation(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    repository_id, run = evaluation_store.find_run(args.run)
    if run["recordState"] != "completed":
        raise types.EvaluationError("observations require a completed run")
    observation = _observation_from_report(
        evaluation_store=evaluation_store,
        repository_id=repository_id,
        run=run,
        report_path=Path(args.report) if args.report else None,
        kind=args.kind,
        supersedes=args.supersedes,
    )
    path = evaluation_store.add_observation(repository_id, observation)
    _print({"repositoryId": repository_id, "runId": args.run, "observationId": path.stem})
    return 0


def command_view(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    repository_id, run = evaluation_store.find_run(args.run)
    if run["schemaVersion"] != 2:
        raise types.EvaluationError("derived evaluation view requires a Schema 2 run")
    view = evaluation_view.derived_evaluation_view(
        run,
        evaluation_store.observations_for_run(repository_id, args.run),
        evaluation_store.annotations_for_run(repository_id, args.run),
    )
    # Presentation only: keep persisted records and comparison view digests unchanged.
    _print({**view, "usageSummary": harness_usage.usage_summary(run, view)})
    return 0


def command_inspect_observation(args: argparse.Namespace) -> int:
    repository_id, observation = _store(args).find_observation(args.observation)
    _print({"repositoryId": repository_id, "observation": observation})
    return 0


def command_list(args: argparse.Namespace) -> int:
    _print({"runs": _store(args).list_runs(args.repository)})
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    repository_id, record = _store(args).find_run(args.run)
    _print({
        "repositoryId": repository_id,
        "record": record,
        "legacyReadOnly": record.get("schemaVersion") == 1,
    })
    return 0


def command_export(args: argparse.Namespace) -> int:
    value = _store(args).export_repository(args.repository)
    if args.output:
        harness_state.atomic_write_text(Path(args.output), types.canonical_text(value), mode=0o600)
        _print({"output": str(Path(args.output).resolve()), "includedCount": value["includedCount"]})
    else:
        _print(value)
    return 0


def command_purge(args: argparse.Namespace) -> int:
    _print(_store(args).purge_repository(args.repository))
    return 0


def command_repair(args: argparse.Namespace) -> int:
    _print(_store(args).repair_repository(args.repository, quarantine=args.quarantine))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    baseline_repository, baseline = evaluation_store.find_run(args.baseline_run)
    treatment_repository, treatment = evaluation_store.find_run(args.treatment_run)
    if baseline_repository != treatment_repository:
        raise compare.ComparisonError("paired runs must belong to one repository")
    plan = types.load_json(Path(args.plan))
    comparison_id = str(evaluation_store.ids.new_uuid())
    pair_id = baseline["comparison"].get("pairId") or treatment["comparison"].get("pairId") or str(evaluation_store.ids.new_uuid())
    comparison_arguments: dict[str, Any] = {}
    if baseline.get("schemaVersion") == 2 and treatment.get("schemaVersion") == 2:
        baseline_view = evaluation_view.derived_evaluation_view(
            baseline,
            evaluation_store.observations_for_run(baseline_repository, baseline["runId"]),
            evaluation_store.annotations_for_run(baseline_repository, baseline["runId"]),
        )
        treatment_view = evaluation_view.derived_evaluation_view(
            treatment,
            evaluation_store.observations_for_run(treatment_repository, treatment["runId"]),
            evaluation_store.annotations_for_run(treatment_repository, treatment["runId"]),
        )

        def correction_count(view: dict[str, Any]) -> float | None:
            item = view["selectedValues"].get("userOutcome.correctionCount")
            if not isinstance(item, dict) or item.get("state") != "measured":
                return None
            value = item.get("value")
            return float(value) if isinstance(value, int) and not isinstance(value, bool) else None

        comparison_arguments = {
            "baseline_view": baseline_view,
            "treatment_view": treatment_view,
            "baseline_corrections": correction_count(baseline_view),
            "treatment_corrections": correction_count(treatment_view),
        }
    value = compare.compare_runs(
        baseline=baseline,
        treatment=treatment,
        plan=plan,
        comparison_id=comparison_id,
        pair_id=pair_id,
        repository_id=baseline_repository,
        created_at=types.timestamp_text(evaluation_store.clock.now_utc()),
        **comparison_arguments,
    )
    evaluation_store.write_auxiliary(baseline_repository, "comparisons", comparison_id, value)
    _print(value)
    return 0


def _load_auxiliary(evaluation_store: store_module.EvaluationStore, repository_id: str, kind: str) -> list[dict[str, Any]]:
    root = evaluation_store.repository_root(repository_id) / kind
    values: list[dict[str, Any]] = []
    if not root.is_dir():
        return values
    with evaluation_store.repository_lock(repository_id):
        for path in sorted(root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if kind == "comparisons":
                    types.validate_comparison_record(value)
                else:
                    types.validate_proposal_record(value)
                values.append(value)
            except (OSError, UnicodeError, json.JSONDecodeError, types.EvaluationError):
                continue
    return values


def _proposal_eligibility(
    *,
    evaluation_store: store_module.EvaluationStore,
    repository_id: str,
    comparisons: list[dict[str, Any]],
    comparison_plan: dict[str, Any] | None,
    task_category: str,
    complexity_level: str,
    impact_level: str,
    evaluation_stratum: str | None = None,
) -> propose.ProposalEligibility:
    if evaluation_stratum is not None and not types.HASH_RE.fullmatch(evaluation_stratum):
        raise types.EvaluationError("evaluation stratum must be a SHA-256 fingerprint")
    plan_sha256 = (
        types.digest_bytes(types.canonical_bytes(comparison_plan))
        if comparison_plan is not None
        else None
    )
    attribution_target = (
        comparison_plan["intervention"]["attributionTarget"]
        if comparison_plan is not None
        else None
    )
    concrete_plan = attribution_target in {"single-factor", "bundle"}
    relevant: list[dict[str, Any]] = []
    reasons: dict[str, set[str]] = {}
    matching_strata: set[str] = set()

    def exclude(comparison_id: str, reason: str) -> None:
        reasons.setdefault(comparison_id, set()).add(reason)

    for comparison_record in comparisons:
        if comparison_record.get("schemaVersion") != 2:
            continue
        if comparison_record.get("repositoryId") != repository_id:
            continue
        stratum = comparison_record["taskStratum"]
        if task_category != "unknown" and stratum["category"] != task_category:
            continue
        if complexity_level != "unknown" and stratum["complexityLevel"] != complexity_level:
            continue
        if impact_level != "unknown" and stratum["impactLevel"] != impact_level:
            continue
        matching_strata.add(comparison_record["evaluationStratumFingerprint"])
        if comparison_record.get("primaryOutcome", {}).get("direction") == "unknown":
            continue
        if (
            evaluation_stratum is not None
            and comparison_record["evaluationStratumFingerprint"] != evaluation_stratum
        ):
            continue
        relevant.append(comparison_record)
        comparison_id = comparison_record["comparisonId"]
        if not concrete_plan or plan_sha256 is None:
            exclude(comparison_id, "verified-comparison-plan-required")
        elif comparison_record["planSha256"] != plan_sha256:
            exclude(comparison_id, "comparison-plan-mismatch")
        if comparison_record["isolationStatus"] != "complete":
            exclude(comparison_id, "comparison-isolation-not-complete")
        delta = comparison_record["configurationDelta"]
        if (
            delta["state"] != "measured"
            or not delta["protocolMatch"]
            or delta["changedFactorCount"] <= 0
            or comparison_record["protocolDeviations"]
        ):
            exclude(comparison_id, "configuration-attribution-ineligible")
        if not comparison_record["resultFingerprintComplete"]:
            exclude(comparison_id, "result-fingerprint-incomplete")

        runs: dict[str, dict[str, Any]] = {}
        effective_runs: dict[str, dict[str, Any]] = {}
        for key, arm in (("baselineRunId", "baseline"), ("treatmentRunId", "treatment")):
            try:
                run = evaluation_store.read_run(
                    repository_id, comparison_record[key], allow_pending=False
                )
                runs[arm] = run
                view = evaluation_view.derived_evaluation_view(
                    run,
                    evaluation_store.observations_for_run(repository_id, run["runId"]),
                    evaluation_store.annotations_for_run(repository_id, run["runId"]),
                )
            except (store_module.StoreError, types.EvaluationError):
                exclude(comparison_id, "derived-view-unavailable")
                break
            if not view["proposalEligible"]:
                for reason in view["proposalIneligibilityReasons"]:
                    exclude(comparison_id, reason)
            effective_runs[arm] = evaluation_view.materialize_run_view(run, view)
            if (
                types.digest_bytes(types.canonical_bytes(view))
                != comparison_record["derivedViewFingerprints"][arm]
            ):
                exclude(comparison_id, "derived-view-changed")
        if len(runs) != 2:
            continue
        if len(effective_runs) == 2 and compare.correctness_gate(
            effective_runs["baseline"], effective_runs["treatment"], comparison_record["correctnessGate"]["policy"]
        )["status"] == "unknown":
            exclude(comparison_id, "correctness-verification-unknown")
        if any(
            not harness_metadata.evaluation_contract_eligible(run)
            for run in runs.values()
        ):
            exclude(comparison_id, "ineligible-evaluation-contract")
        patch_scope_fingerprint = (
            comparison_plan["patchScopeProfileFingerprint"]
            if comparison_plan is not None
            else None
        )
        if patch_scope_fingerprint is not None:
            for arm in ("baseline", "treatment"):
                patch_scope = runs[arm]["result"]["patchScope"]
                if not (
                    patch_scope["state"] == "measured"
                    and patch_scope["completeness"] == "complete"
                    and patch_scope["profileFingerprint"] == patch_scope_fingerprint
                    and patch_scope["withinDeclaredScope"] is True
                    and patch_scope["maximumChangedPathsExceeded"] is False
                ):
                    exclude(comparison_id, f"{arm}-patch-scope-attribution-excluded")

    if evaluation_stratum is not None and evaluation_stratum not in matching_strata:
        raise types.EvaluationError(
            f"requested evaluation stratum was not found: {evaluation_stratum}"
        )

    candidates = [
        item for item in relevant if item["comparisonId"] not in reasons
    ]
    run_uses: dict[str, list[str]] = {}
    pair_uses: dict[tuple[str, str], list[str]] = {}
    for comparison_record in candidates:
        comparison_id = comparison_record["comparisonId"]
        pair = (
            comparison_record["baselineRunId"],
            comparison_record["treatmentRunId"],
        )
        pair_uses.setdefault(pair, []).append(comparison_id)
        for run_id in pair:
            run_uses.setdefault(run_id, []).append(comparison_id)
    non_independent = {
        comparison_id
        for comparison_ids in (*pair_uses.values(), *run_uses.values())
        if len(comparison_ids) > 1
        for comparison_id in comparison_ids
    }
    for comparison_id in non_independent:
        exclude(comparison_id, "non-independent-evidence-unit")

    eligible_strata = sorted({
        item["evaluationStratumFingerprint"]
        for item in relevant
        if item["comparisonId"] not in reasons
    })
    if evaluation_stratum is None and concrete_plan and len(eligible_strata) > 1:
        raise types.EvaluationError(
            "multiple concrete-eligible evaluation strata require --evaluation-stratum: "
            + ", ".join(eligible_strata)
        )

    relevant_ids = tuple(sorted(item["comparisonId"] for item in relevant))
    basis_ids = tuple(
        sorted(
            item["comparisonId"]
            for item in relevant
            if item["comparisonId"] not in reasons
        )
    )
    return propose.ProposalEligibility(
        relevant_comparison_ids=relevant_ids,
        attribution_basis_ids=basis_ids,
        excluded_comparison_ids=tuple(sorted(reasons)),
        exclusion_reasons={
            comparison_id: tuple(sorted(items))
            for comparison_id, items in sorted(reasons.items())
        },
        verified_plan_sha256=plan_sha256,
        attribution_target=attribution_target,
        concrete_attribution_allowed=concrete_plan and bool(basis_ids),
    )


def command_propose(args: argparse.Namespace) -> int:
    evaluation_store = _store(args)
    proposal_id = str(evaluation_store.ids.new_uuid())
    comparisons = _load_auxiliary(evaluation_store, args.repository, "comparisons")
    comparison_plan = None
    if args.comparison_plan:
        comparison_plan = types.load_json(Path(args.comparison_plan))
        types.validate_comparison_plan(comparison_plan)
        if comparison_plan.get("schemaVersion") != 2:
            raise types.EvaluationError("Schema 2 proposals require a Schema 2 comparison plan")
    eligibility = _proposal_eligibility(
        evaluation_store=evaluation_store,
        repository_id=args.repository,
        comparisons=comparisons,
        comparison_plan=comparison_plan,
        task_category=args.category,
        complexity_level=args.complexity,
        impact_level=args.impact,
        evaluation_stratum=args.evaluation_stratum,
    )
    warnings = {
        reason
        for reasons in eligibility.exclusion_reasons.values()
        for reason in reasons
    }
    value = propose.proposal_from_comparisons(
        repository_id=args.repository,
        proposal_id=proposal_id,
        created_at=types.timestamp_text(evaluation_store.clock.now_utc()),
        comparisons=comparisons,
        task_category=args.category,
        complexity_level=args.complexity,
        impact_level=args.impact,
        evaluation_stratum=args.evaluation_stratum,
        comparison_plan=comparison_plan,
        eligibility=eligibility,
    )
    evaluation_store.write_auxiliary(args.repository, "proposals", proposal_id, value)
    if eligibility.excluded_comparison_ids:
        print(
            f"warning: {len(eligibility.excluded_comparison_ids)} comparisons were excluded from configuration attribution: "
            f"{', '.join(sorted(warnings))}",
            file=sys.stderr,
        )
    _print(
        {
            "proposal": value,
            "warnings": sorted(warnings),
            "excludedComparisonRefs": list(eligibility.excluded_comparison_ids),
        }
        if args.report_envelope
        else value
    )
    return 0


def _verification_profile(path: Path) -> dict[str, Any]:
    value = types.load_json(path)
    if not isinstance(value, dict):
        raise types.EvaluationError("verification profile must be an object")
    required = {"schemaVersion", "id", "kind", "argv", "timeoutSeconds"}
    if set(value) != required or value.get("schemaVersion") != 1:
        raise types.EvaluationError("verification profile fields are invalid")
    if not isinstance(value["id"], str) or not value["id"]:
        raise types.EvaluationError("verification profile id must be non-empty")
    if value["kind"] not in {"unit-test", "integration-test", "lint", "type-check", "schema", "custom"}:
        raise types.EvaluationError("verification profile kind is invalid")
    if not isinstance(value["argv"], list) or not value["argv"] or not all(isinstance(item, str) and item for item in value["argv"]):
        raise types.EvaluationError("verification profile argv must be a non-empty string array")
    if isinstance(value["timeoutSeconds"], bool) or not isinstance(value["timeoutSeconds"], (int, float)) or value["timeoutSeconds"] <= 0:
        raise types.EvaluationError("verification profile timeoutSeconds must be positive")
    return value


def _run_verification(
    *,
    root: Path,
    profile: dict[str, Any],
    profile_digest: str,
    check_ref: str,
) -> tuple[dict[str, Any], bool]:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process: subprocess.Popen[Any] | None = None
    try:
        process = subprocess.Popen(
            profile["argv"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        exit_code = process.wait(timeout=float(profile["timeoutSeconds"]))
        result = "passed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        exit_code = None
        result = "failed"
    except OSError as exc:
        raise types.EvaluationError("verification process could not be started") from exc
    finally:
        cleanup_verified = (
            capture._terminate_process_tree(process) if process is not None else False
        )
    exit_measurement = (
        types.measurement(
            exit_code,
            unit="exit-code",
            state="measured",
            source="verification-runner",
            fidelity="exact",
            completeness="complete",
        )
        if exit_code is not None
        else types.unavailable("exit-code")
    )
    return (
        {
            "checkRef": check_ref,
            "profileFingerprint": profile_digest,
            "kind": profile["kind"],
            "result": result,
            "exitCode": exit_measurement,
        },
        cleanup_verified,
    )


def _record_verification_repository_state(
    record: dict[str, Any],
    *,
    pre_verification_signature: str | None,
    post_verification_signature: str | None,
    quiescent: bool | None,
) -> None:
    gap: str | None = None
    if (
        pre_verification_signature is None
        or post_verification_signature is None
        or quiescent is None
    ):
        gap = "verification-repository-state-unavailable"
    elif (
        not quiescent
        or pre_verification_signature != post_verification_signature
    ):
        gap = "verification-repository-state-mutated"
    if gap is None:
        return
    comparison = record["comparison"]
    comparison["isolationGaps"] = sorted(set(comparison["isolationGaps"] + [gap]))
    if comparison["isolationStatus"] == "complete":
        comparison["isolationStatus"] = "partial"


def _lexical_tree_files(
    root: Path,
    relative_directory: str,
    *,
    recursive: bool,
    suffix: str | None = None,
) -> tuple[list[str], list[str]]:
    """List regular project-context files without following filesystem links."""
    try:
        directory = harness_state.resolve_inside(root, relative_directory)
    except harness_state.StateError as exc:
        raise types.EvaluationError(str(exc)) from exc
    if not directory.exists() and not directory.is_symlink():
        return [], []
    try:
        metadata = directory.lstat()
    except OSError:
        return [], [PROJECT_CONTEXT_GAP]
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
        return [], [PROJECT_CONTEXT_GAP]
    if not stat.S_ISDIR(metadata.st_mode):
        return [], [PROJECT_CONTEXT_GAP]

    files: list[str] = []
    gaps: list[str] = []

    def visit(current: Path) -> None:
        try:
            children = sorted(current.iterdir(), key=lambda value: value.name.casefold())
        except OSError:
            gaps.append(PROJECT_CONTEXT_GAP)
            return
        for child in children:
            try:
                child_metadata = child.lstat()
            except OSError:
                gaps.append(PROJECT_CONTEXT_GAP)
                continue
            child_attributes = getattr(child_metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(child_metadata.st_mode) or (
                reparse_flag and child_attributes & reparse_flag
            ):
                gaps.append(PROJECT_CONTEXT_GAP)
                continue
            if stat.S_ISDIR(child_metadata.st_mode):
                if recursive:
                    visit(child)
                continue
            if not stat.S_ISREG(child_metadata.st_mode):
                gaps.append(PROJECT_CONTEXT_GAP)
                continue
            if suffix is not None and child.suffix.casefold() != suffix.casefold():
                continue
            relative = child.relative_to(root.resolve()).as_posix()
            try:
                harness_state.portable_path_key(relative)
            except harness_state.StateError:
                gaps.append(PROJECT_CONTEXT_GAP)
                continue
            if len(files) >= PAIRED_OVERLAY_MAX_FILES:
                raise types.EvaluationError(
                    "paired-run project context exceeds the file limit"
                )
            files.append(relative)

    visit(directory)
    return files, gaps


def _capture_project_context(
    root: Path,
    *,
    managed_paths: list[str],
    evidence_paths: set[str],
) -> dict[str, Any]:
    """Capture unmanaged Codex context that can change a paired task's behavior."""
    try:
        instruction_candidates = harness_state.project_instruction_candidates(root)
        source_instruction = harness_state.active_instruction_relative(root)
    except harness_state.StateError as exc:
        raise types.EvaluationError(
            f"could not discover project instruction context: {exc}"
        ) from exc

    candidate_kinds: dict[tuple[str, ...], tuple[str, str]] = {}
    gaps: list[str] = []

    def add_candidate(relative: str, kind: str) -> None:
        key = harness_state.portable_path_key(relative)
        existing = candidate_kinds.get(key)
        if existing is not None and existing[0] != relative:
            raise types.EvaluationError(
                "paired project context has a portable path collision: "
                f"{existing[0]} vs {relative}"
            )
        candidate_kinds[key] = (relative, kind)

    config_relative = harness_state.PROJECT_CONFIG_RELATIVE
    config_path = root / config_relative
    project_config_present = config_path.exists() or config_path.is_symlink()
    if project_config_present:
        add_candidate(config_relative, "project-config")
        gaps.append(PROJECT_CONFIG_LOAD_GAP)

    for relative in instruction_candidates:
        path = root.joinpath(*Path(relative).parts)
        if path.exists() or path.is_symlink():
            add_candidate(relative, "instruction-candidate")

    agent_paths, agent_gaps = _lexical_tree_files(
        root, ".codex/agents", recursive=False, suffix=".toml"
    )
    skill_paths, skill_gaps = _lexical_tree_files(
        root, ".agents/skills", recursive=True
    )
    gaps.extend(agent_gaps)
    gaps.extend(skill_gaps)
    for relative in agent_paths:
        add_candidate(relative, "custom-agent")
    for relative in skill_paths:
        add_candidate(relative, "project-skill")

    excluded = {
        harness_state.portable_path_key(relative)
        for relative in [*managed_paths, *evidence_paths]
    }
    selected = [
        value for key, value in candidate_kinds.items() if key not in excluded
    ]
    selected.sort(key=lambda value: harness_state.portable_path_key(value[0]))
    project_agent_config_count = sum(
        1 for _relative, kind in selected if kind == "custom-agent"
    )
    if project_agent_config_count:
        gaps.append(PROJECT_AGENT_LOAD_GAP)
    if len(selected) > PAIRED_OVERLAY_MAX_FILES:
        raise types.EvaluationError("paired-run project context exceeds the file limit")
    try:
        tracked = set(
            harness_workspace.tracked_paths(root, [relative for relative, _kind in selected])
        )
    except harness_workspace.WorkspaceError as exc:
        raise types.EvaluationError(str(exc)) from exc

    files: list[dict[str, Any]] = []
    total_bytes = 0
    for relative, kind in selected:
        try:
            path, present = harness_state.resolve_lexical_regular_inside(
                root,
                relative,
                must_exist=True,
                label="project context",
            )
        except harness_state.StateError:
            gaps.append(PROJECT_CONTEXT_GAP)
            continue
        if not present:
            gaps.append(PROJECT_CONTEXT_GAP)
            continue
        try:
            data = path.read_bytes()
        except OSError:
            gaps.append(PROJECT_CONTEXT_GAP)
            continue
        total_bytes += len(data)
        if total_bytes > PAIRED_OVERLAY_MAX_BYTES:
            raise types.EvaluationError(
                "paired-run project context exceeds the byte limit"
            )
        files.append(
            {
                "path": relative,
                "kind": kind,
                "data": data,
                "mode": harness_state.current_mode(path),
                "contentSha256": types.digest_bytes(data),
                "tracked": relative in tracked,
            }
        )
    return {
        "files": files,
        "instructionCandidates": instruction_candidates,
        "sourceInstruction": source_instruction,
        "projectConfigPresent": project_config_present,
        "projectConfigLoadVerified": False if project_config_present else None,
        "projectAgentConfigCount": project_agent_config_count,
        "projectAgentLoadVerified": False if project_agent_config_count else None,
        "projectAgentDependenciesVerified": False if project_agent_config_count else None,
        "isolationGaps": sorted(set(gaps)),
    }


def _capture_local_harness_snapshot(root: Path, source_commit: str) -> dict[str, Any]:
    """Capture an untracked installation in a clean Git root for isolated evaluation."""
    try:
        worktree_count = harness_workspace.require_exclusive_info_exclude(root)
    except harness_workspace.WorkspaceError as exc:
        raise types.EvaluationError(str(exc)) from exc
    report = validate_harness.Validator(root).run()
    if not report["valid"]:
        detail = "; ".join(report["errors"][:5]) or "installed validation failed"
        raise types.EvaluationError(
            "paired-run requires a valid project-local Harness installation: " + detail
        )
    raw_manifest_path = root / ".harness" / "manifest.json"
    if raw_manifest_path.is_symlink():
        raise types.EvaluationError("paired-run source manifest must not be a symbolic link")
    try:
        harness_state.resolve_inside(root, ".harness/manifest.json", must_exist=True)
    except harness_state.StateError as exc:
        raise types.EvaluationError(str(exc)) from exc
    manifest_path, manifest = harness_state.load_manifest(root)
    if manifest is None:
        raise types.EvaluationError("paired-run requires a Harness manifest")
    if harness_state.transaction_status(root) is not None:
        raise types.EvaluationError("paired-run refuses a pending Harness transaction")
    if harness_metadata.artifact_contract_state(manifest) != "current":
        raise types.EvaluationError(
            "paired-run requires a compatible project-local artifact contract"
        )
    workspace = manifest.get("workspace")
    if (
        not isinstance(workspace, dict)
        or workspace.get("scope") != harness_workspace.LOCAL_SCOPE
        or workspace.get("kind") not in harness_workspace.GIT_WORKSPACE_KINDS
    ):
        raise types.EvaluationError("paired-run requires a project-local Harness installation at a Git root")
    entries = manifest.get("managedFiles")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise types.EvaluationError("paired-run manifest managedFiles must be objects")
    project = manifest.get("project")
    topology = manifest.get("topology")
    project_evidence = project.get("evidence", []) if isinstance(project, dict) else []
    evidence_paths = {
        item.get("path")
        for item in project_evidence
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if isinstance(topology, dict):
        evidence_paths.update(harness_topology.evidence_paths(topology))
    scoped_instruction_paths = {
        item["path"] for values in [project_evidence] +
        [values for _, values in harness_topology.iter_evidence(topology if isinstance(topology, dict) else {})]
        for item in values if isinstance(values, list) and isinstance(item, dict)
        and item.get("contentScope") == harness_state.INSTRUCTION_EVIDENCE_SCOPE
        and isinstance(item.get("path"), str)
    }
    # The managed overlay already captures these exact user bytes. A second
    # full-file evidence overlay would restore the Harness pointer in baseline.
    evidence_paths -= scoped_instruction_paths & {
        entry.get("path") for entry in entries if entry.get("kind") == "managed-block"
    }
    manifest_bytes = manifest_path.read_bytes()
    managed_paths = [entry.get("path") for entry in entries]
    if not all(isinstance(path, str) for path in managed_paths):
        raise types.EvaluationError("paired-run manifest contains an invalid managed path")
    try:
        for relative in sorted(evidence_paths):
            harness_state.validate_evidence_relative(relative)
        harness_state.validate_file_namespace(
            [*managed_paths, ".harness/manifest.json", *sorted(evidence_paths)],
            label="paired Harness and evidence paths",
        )
        harness_workspace.validate_manifest_protection(root, workspace, managed_paths)
        if harness_workspace.tracked_paths(root, [*managed_paths, ".harness"]):
            raise types.EvaluationError("paired-run requires untracked Harness targets to isolate its baseline")
        tracked_evidence = set(harness_workspace.tracked_paths(root, evidence_paths))
    except (harness_state.StateError, harness_workspace.WorkspaceError) as exc:
        raise types.EvaluationError(str(exc)) from exc
    project_context = _capture_project_context(
        root,
        managed_paths=managed_paths,
        evidence_paths=evidence_paths,
    )
    if (
        1
        + len(entries)
        + len(evidence_paths)
        + len(project_context["files"])
        > PAIRED_OVERLAY_MAX_FILES
    ):
        raise types.EvaluationError("paired-run overlay exceeds the file limit")

    captured: list[dict[str, Any]] = []
    evidence_captured: list[dict[str, Any]] = []
    total_bytes = len(manifest_bytes)
    if total_bytes > PAIRED_OVERLAY_MAX_BYTES:
        raise types.EvaluationError("paired-run Harness overlay exceeds the byte limit")
    for entry in entries:
        relative = entry["path"]
        kind = entry.get("kind", "file")
        if kind not in {"file", "managed-block"}:
            raise types.EvaluationError(f"unsupported paired overlay entry kind: {kind!r}")
        try:
            path = harness_state.resolve_inside(root, relative, must_exist=True)
        except harness_state.StateError as exc:
            raise types.EvaluationError(str(exc)) from exc
        if path.is_symlink() or not path.is_file():
            raise types.EvaluationError(f"paired overlay source is not a regular file: {relative}")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > PAIRED_OVERLAY_MAX_BYTES:
            raise types.EvaluationError("paired-run Harness overlay exceeds the byte limit")
        captured.append(
            {
                "path": relative,
                "kind": kind,
                "data": data,
                "mode": harness_state.current_mode(path),
                "contentSha256": types.digest_bytes(data),
            }
        )
    for relative in sorted(evidence_paths):
        path, exists = _evidence_target(root, relative)
        if not exists:
            raise types.EvaluationError(f"paired evidence source is missing: {relative}")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > PAIRED_OVERLAY_MAX_BYTES:
            raise types.EvaluationError("paired-run Harness overlay exceeds the byte limit")
        evidence_captured.append(
            {
                "path": relative,
                "data": data,
                "mode": harness_state.current_mode(path),
                "contentSha256": types.digest_bytes(data),
                "tracked": relative in tracked_evidence,
            }
        )
    for item in project_context["files"]:
        total_bytes += len(item["data"])
        if total_bytes > PAIRED_OVERLAY_MAX_BYTES:
            raise types.EvaluationError("paired-run overlay exceeds the byte limit")

    manifest_mode = harness_state.current_mode(manifest_path)
    treatment_manifest = copy.deepcopy(manifest)
    treatment_manifest["workspace"]["kind"] = "git-repository"
    treatment_manifest_bytes = (
        json.dumps(treatment_manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    identity = {
        "sourceManifestSha256": types.digest_bytes(manifest_bytes),
        "treatmentManifestSha256": types.digest_bytes(treatment_manifest_bytes),
        "files": [
            {
                "path": item["path"],
                "kind": item["kind"],
                "mode": harness_state.mode_text(item["mode"]),
                "contentSha256": item["contentSha256"],
            }
            for item in captured
        ],
        "evidence": [
            {
                "path": item["path"],
                "mode": harness_state.mode_text(item["mode"]),
                "contentSha256": item["contentSha256"],
                "tracked": item["tracked"],
            }
            for item in evidence_captured
        ],
        "projectContext": [
            {
                "path": item["path"],
                "kind": item["kind"],
                "mode": harness_state.mode_text(item["mode"]),
                "contentSha256": item["contentSha256"],
                "tracked": item["tracked"],
            }
            for item in project_context["files"]
        ],
        "instructionCandidates": project_context["instructionCandidates"],
        "sourceInstruction": project_context["sourceInstruction"],
        "projectConfigPresent": project_context["projectConfigPresent"],
        "projectConfigLoadVerified": project_context["projectConfigLoadVerified"],
        "projectAgentConfigCount": project_context["projectAgentConfigCount"],
        "projectAgentLoadVerified": project_context["projectAgentLoadVerified"],
        "projectAgentDependenciesVerified": project_context[
            "projectAgentDependenciesVerified"
        ],
    }
    snapshot = {
        "sourceCommit": source_commit,
        "sourceManifestBytes": manifest_bytes,
        "sourceManifestSha256": identity["sourceManifestSha256"],
        "treatmentManifest": treatment_manifest,
        "treatmentManifestBytes": treatment_manifest_bytes,
        "treatmentManifestSha256": identity["treatmentManifestSha256"],
        "manifestMode": manifest_mode,
        "managedFiles": captured,
        "evidenceFiles": evidence_captured,
        "projectContextFiles": project_context["files"],
        "instructionCandidates": project_context["instructionCandidates"],
        "sourceInstruction": project_context["sourceInstruction"],
        "projectConfigPresent": project_context["projectConfigPresent"],
        "projectConfigLoadVerified": project_context["projectConfigLoadVerified"],
        "projectAgentConfigCount": project_context["projectAgentConfigCount"],
        "projectAgentLoadVerified": project_context["projectAgentLoadVerified"],
        "projectAgentDependenciesVerified": project_context[
            "projectAgentDependenciesVerified"
        ],
        "isolationGaps": project_context["isolationGaps"],
        "managedPaths": managed_paths,
        "overlaySha256": types.digest_bytes(types.canonical_bytes(identity)),
        "worktreeCount": worktree_count,
    }
    _verify_local_harness_snapshot(root, snapshot)
    return snapshot


def _verify_local_harness_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    """Fail if the source installation changes during its bounded capture."""
    if _git(root, "rev-parse", "HEAD").stdout.strip() != snapshot["sourceCommit"]:
        raise types.EvaluationError("paired-run source commit changed during preflight")
    if _git(root, "status", "--porcelain").stdout.strip():
        raise types.EvaluationError("paired-run source repository changed during preflight")
    try:
        if harness_workspace.require_exclusive_info_exclude(root) != snapshot["worktreeCount"]:
            raise types.EvaluationError("paired-run source worktree count changed during preflight")
    except harness_workspace.WorkspaceError as exc:
        raise types.EvaluationError(str(exc)) from exc
    manifest_path = root / ".harness" / "manifest.json"
    if not manifest_path.is_file() or manifest_path.read_bytes() != snapshot["sourceManifestBytes"]:
        raise types.EvaluationError("paired-run source manifest changed during preflight")
    if harness_state.current_mode(manifest_path) != snapshot["manifestMode"]:
        raise types.EvaluationError("paired-run source manifest mode changed during preflight")
    for item in snapshot["managedFiles"]:
        try:
            path = harness_state.resolve_inside(root, item["path"], must_exist=True)
        except harness_state.StateError as exc:
            raise types.EvaluationError(str(exc)) from exc
        if (
            path.is_symlink()
            or not path.is_file()
            or path.read_bytes() != item["data"]
            or harness_state.current_mode(path) != item["mode"]
        ):
            raise types.EvaluationError(
                f"paired-run source managed file changed during preflight: {item['path']}"
            )
    for item in snapshot["evidenceFiles"]:
        path, exists = _evidence_target(root, item["path"])
        if (
            not exists
            or path.read_bytes() != item["data"]
            or harness_state.current_mode(path) != item["mode"]
        ):
            raise types.EvaluationError(
                f"paired-run source evidence changed during preflight: {item['path']}"
            )
    for item in snapshot["projectContextFiles"]:
        try:
            path, exists = harness_state.resolve_lexical_regular_inside(
                root,
                item["path"],
                must_exist=True,
                label="project context",
            )
        except harness_state.StateError as exc:
            raise types.EvaluationError(str(exc)) from exc
        if (
            not exists
            or path.read_bytes() != item["data"]
            or harness_state.current_mode(path) != item["mode"]
        ):
            raise types.EvaluationError(
                f"paired-run source project context changed during preflight: {item['path']}"
            )


def _clone_local_evaluation_arm(source: Path, destination: Path, commit: str) -> None:
    """Create an independent local clone so arm metadata is never shared with the source."""
    if destination.exists():
        raise types.EvaluationError("paired-run arm destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--local",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(source.resolve()),
                str(destination.resolve()),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _git(destination, "checkout", "--detach", commit)
        _git(destination, "remote", "remove", "origin")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise types.EvaluationError("could not create an independent local evaluation clone") from exc
    if _git(destination, "rev-parse", "HEAD").stdout.strip() != commit:
        raise types.EvaluationError("paired-run clone does not match the source commit")
    if _git(destination, "status", "--porcelain").stdout.strip():
        raise types.EvaluationError("paired-run clone is not clean before materialization")
    if _git(destination, "remote").stdout.strip():
        raise types.EvaluationError("paired-run clone retained a Git remote")
    try:
        harness_workspace.require_exclusive_info_exclude(destination)
    except harness_workspace.WorkspaceError as exc:
        raise types.EvaluationError(str(exc)) from exc


def _assert_overlay_targets_unused(root: Path, snapshot: dict[str, Any]) -> None:
    for relative in [*snapshot["managedPaths"], ".harness/manifest.json"]:
        try:
            target = harness_state.resolve_inside(root, relative)
        except harness_state.StateError as exc:
            raise types.EvaluationError(str(exc)) from exc
        if target.exists() or target.is_symlink():
            raise types.EvaluationError(
                f"paired-run clone contains a conflicting Harness target: {relative}"
            )


def _evidence_target(root: Path, relative: str) -> tuple[Path, bool]:
    """Resolve an evidence path without following lexical symlink/reparse ancestors."""
    try:
        harness_state.validate_evidence_relative(relative)
        return harness_state.resolve_lexical_regular_inside(
            root,
            relative,
            label="paired evidence target",
        )
    except harness_state.StateError as exc:
        raise types.EvaluationError(str(exc)) from exc


def _preflight_evidence_targets(
    roots: tuple[Path, Path], snapshot: dict[str, Any]
) -> None:
    """Validate every evidence target in both arms before the first evidence write."""
    for root in roots:
        for item in snapshot["evidenceFiles"]:
            _path, exists = _evidence_target(root, item["path"])
            if item["tracked"] and not exists:
                raise types.EvaluationError(
                    f"tracked paired evidence is missing from clone: {item['path']}"
                )


def _project_context_target(root: Path, relative: str) -> tuple[Path, bool]:
    try:
        return harness_state.resolve_lexical_regular_inside(
            root,
            relative,
            label="paired project context target",
        )
    except harness_state.StateError as exc:
        raise types.EvaluationError(str(exc)) from exc


def _preflight_project_context_targets(
    roots: tuple[Path, Path], snapshot: dict[str, Any]
) -> None:
    """Validate all context destinations in both arms before any paired write."""
    for root in roots:
        for item in snapshot["projectContextFiles"]:
            _path, exists = _project_context_target(root, item["path"])
            if item["tracked"] and not exists:
                raise types.EvaluationError(
                    f"tracked paired project context is missing from clone: {item['path']}"
                )


def _write_harness_overlay(root: Path, snapshot: dict[str, Any]) -> None:
    _assert_overlay_targets_unused(root, snapshot)
    for item in snapshot["managedFiles"]:
        path = harness_state.resolve_inside(root, item["path"])
        harness_state.atomic_write_bytes(path, item["data"], mode=item["mode"])
    manifest_path = harness_state.resolve_inside(root, ".harness/manifest.json")
    harness_state.atomic_write_bytes(
        manifest_path,
        snapshot["treatmentManifestBytes"],
        mode=snapshot["manifestMode"],
    )


def _write_evidence_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    """Give both arms the exact evidence bytes used by the source manifest."""
    for item in snapshot["evidenceFiles"]:
        path, _exists = _evidence_target(root, item["path"])
        harness_state.atomic_write_bytes(path, item["data"], mode=item["mode"])


def _write_project_context_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    """Materialize exact project context bytes in one disposable arm."""
    for item in snapshot["projectContextFiles"]:
        path, _exists = _project_context_target(root, item["path"])
        harness_state.atomic_write_bytes(path, item["data"], mode=item["mode"])


def _assert_evidence_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    for item in snapshot["evidenceFiles"]:
        path, exists = _evidence_target(root, item["path"])
        if (
            not exists
            or path.read_bytes() != item["data"]
            or not harness_state.mode_matches(path, item["mode"])
        ):
            raise types.EvaluationError(
                f"paired evidence differs from the captured snapshot: {item['path']}"
            )


def _assert_project_context_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    for item in snapshot["projectContextFiles"]:
        path, exists = _project_context_target(root, item["path"])
        if (
            not exists
            or path.read_bytes() != item["data"]
            or not harness_state.mode_matches(path, item["mode"])
        ):
            raise types.EvaluationError(
                f"paired project context differs from the captured snapshot: {item['path']}"
            )


def _instruction_remainder(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise types.EvaluationError("paired instruction target is not a regular file")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError) as exc:
        raise types.EvaluationError("paired instruction target is not UTF-8 text") from exc
    if harness_state.BEGIN_MARKER not in text and harness_state.END_MARKER not in text:
        return data
    try:
        block = harness_state.extract_managed_block(text)
    except harness_state.StateError as exc:
        raise types.EvaluationError(str(exc)) from exc
    if text == f"{block.rstrip()}\n":
        return None
    return harness_state.instruction_user_content(data)


def _changed_project_paths(root: Path) -> set[str]:
    changed = {
        value
        for value in _git(root, "diff", "--name-only", "-z", "HEAD").stdout.split("\0")
        if value
    }
    untracked = {
        value
        for value in _git(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        ).stdout.split("\0")
        if value
    }
    return {value.replace("\\", "/") for value in changed | untracked}


def _assert_materialization_invariants(
    baseline_root: Path,
    treatment_root: Path,
    snapshot: dict[str, Any],
    removal: dict[str, Any],
) -> None:
    """Check paired fidelity immediately before synthetic task-base creation."""
    _assert_baseline_isolated(baseline_root, removal["removed"])
    _assert_evidence_snapshot(baseline_root, snapshot)
    _assert_evidence_snapshot(treatment_root, snapshot)
    _assert_project_context_snapshot(baseline_root, snapshot)
    _assert_project_context_snapshot(treatment_root, snapshot)
    if _git(baseline_root, "rev-parse", "HEAD").stdout.strip() != snapshot["sourceCommit"]:
        raise types.EvaluationError("paired baseline commit changed during materialization")
    if _git(treatment_root, "rev-parse", "HEAD").stdout.strip() != snapshot["sourceCommit"]:
        raise types.EvaluationError("paired treatment commit changed during materialization")
    if _git(baseline_root, "remote").stdout.strip() or _git(treatment_root, "remote").stdout.strip():
        raise types.EvaluationError("paired materialization retained a Git remote")

    allowed = {
        *snapshot["managedPaths"],
        ".harness/manifest.json",
        *(item["path"] for item in snapshot["evidenceFiles"]),
        *(item["path"] for item in snapshot["projectContextFiles"]),
    }
    for root in (baseline_root, treatment_root):
        unexpected = _changed_project_paths(root) - allowed
        if unexpected:
            raise types.EvaluationError(
                "paired materialization changed a non-Harness project path: "
                + sorted(unexpected)[0]
            )
    for item in snapshot["managedFiles"]:
        if item["kind"] != "managed-block":
            continue
        baseline = harness_state.resolve_inside(baseline_root, item["path"])
        treatment = harness_state.resolve_inside(treatment_root, item["path"])
        if _instruction_remainder(baseline) != _instruction_remainder(treatment):
            raise types.EvaluationError(
                f"paired instruction user content differs between arms: {item['path']}"
            )
    try:
        treatment_instruction = harness_state.active_instruction_relative(treatment_root)
        baseline_instruction = harness_state.active_instruction_relative(baseline_root)
    except harness_state.StateError as exc:
        raise types.EvaluationError(
            f"paired instruction discovery failed after materialization: {exc}"
        ) from exc
    if treatment_instruction != snapshot["sourceInstruction"]:
        raise types.EvaluationError(
            "paired treatment changed the active project instruction candidate"
        )
    if baseline_instruction in {
        relative
        for relative, kind in removal["removed"]
        if kind == "file"
    }:
        raise types.EvaluationError(
            "paired baseline reactivated a removed Harness instruction artifact"
        )


def _materialize_paired_arms(
    baseline_root: Path,
    treatment_root: Path,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Create isolated baseline and treatment states before any Codex process starts."""
    _assert_overlay_targets_unused(baseline_root, snapshot)
    _assert_overlay_targets_unused(treatment_root, snapshot)
    _preflight_evidence_targets((baseline_root, treatment_root), snapshot)
    _preflight_project_context_targets((baseline_root, treatment_root), snapshot)
    _write_evidence_snapshot(baseline_root, snapshot)
    _write_evidence_snapshot(treatment_root, snapshot)
    _write_project_context_snapshot(baseline_root, snapshot)
    _write_project_context_snapshot(treatment_root, snapshot)

    _write_harness_overlay(baseline_root, snapshot)
    removed = _remove_managed_baseline(baseline_root)
    _assert_baseline_isolated(baseline_root, removed["removed"])

    try:
        protection = harness_workspace.plan_local_protection(
            treatment_root, "git-repository", snapshot["managedPaths"]
        )
        harness_workspace.apply_local_protection(
            treatment_root, protection, snapshot["managedPaths"]
        )
    except harness_workspace.WorkspaceError as exc:
        raise types.EvaluationError(str(exc)) from exc
    _write_harness_overlay(treatment_root, snapshot)
    treatment_report = validate_harness.Validator(treatment_root).run()
    if not treatment_report["valid"]:
        detail = "; ".join(treatment_report["errors"][:5]) or "installed validation failed"
        raise types.EvaluationError(
            "paired-run treatment materialization is invalid: " + detail
        )
    manifest_hash, _topology_hash = _manifest_metadata(treatment_root)
    if manifest_hash != snapshot["treatmentManifestSha256"]:
        raise types.EvaluationError("paired-run treatment manifest changed during materialization")
    _assert_materialization_invariants(
        baseline_root, treatment_root, snapshot, removed
    )
    return {
        "removed": removed["removed"],
        "isolationGaps": sorted(
            set(removed["isolationGaps"] + snapshot["isolationGaps"])
        ),
        "baselineInstruction": harness_state.active_instruction_relative(baseline_root),
        "treatmentInstruction": harness_state.active_instruction_relative(treatment_root),
    }


def _remove_managed_baseline(root: Path) -> dict[str, Any]:
    manifest_path = root / ".harness" / "manifest.json"
    if not manifest_path.is_file():
        raise types.EvaluationError("paired baseline requires a Harness manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed: list[tuple[str, str]] = []
    isolation_gaps: list[str] = []
    for entry in manifest.get("managedFiles", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise types.EvaluationError("manifest managedFiles entry is invalid")
        target = harness_state.resolve_inside(root, entry["path"])
        if entry.get("kind", "file") == "managed-block":
            if not target.is_file():
                raise types.EvaluationError(f"managed instruction file is missing: {entry['path']}")
            data = target.read_bytes()
            text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            block = harness_state.extract_managed_block(text)
            if text == f"{block.rstrip()}\n":
                target.unlink()
            else:
                cleaned = harness_state.instruction_user_content(data)
                harness_state.atomic_write_bytes(
                    target, cleaned, mode=harness_state.current_mode(target)
                )
                isolation_gaps.append("baseline-instruction-provenance-unavailable")
            removed.append((entry["path"], "managed-block"))
        else:
            if target.is_file():
                target.unlink()
            removed.append((entry["path"], "file"))
    harness_root = root / ".harness"
    if harness_root.is_dir():
        shutil.rmtree(harness_root)
    return {
        "removed": removed,
        "isolationGaps": sorted(set(isolation_gaps)),
    }


def _assert_baseline_isolated(
    root: Path, removed: list[tuple[str, str]] | dict[str, Any]
) -> None:
    if isinstance(removed, dict):
        removed = removed["removed"]
    if (root / ".harness").exists():
        raise types.EvaluationError("baseline still contains Harness project state")
    for relative, kind in removed:
        target = harness_state.resolve_inside(root, relative)
        if kind == "file" and target.exists():
            raise types.EvaluationError(f"baseline still contains managed artifact: {relative}")
        if kind == "managed-block" and target.is_file():
            text = target.read_text(encoding="utf-8")
            if harness_state.BEGIN_MARKER in text or harness_state.END_MARKER in text:
                raise types.EvaluationError(f"baseline still contains a managed instruction block: {relative}")


def _git_blob(root: Path, object_id: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root.resolve()), "cat-file", "blob", object_id],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise types.EvaluationError("could not read a paired task-base blob") from exc


def _git_blob_for_worktree_bytes(root: Path, relative: str, data: bytes) -> tuple[str, bytes]:
    """Return Git's canonical blob identity for exact worktree bytes at one path."""
    try:
        process = subprocess.run(
            [
                "git",
                "-C",
                str(root.resolve()),
                "hash-object",
                "-w",
                f"--path={relative}",
                "--stdin",
            ],
            check=True,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise types.EvaluationError(
            f"could not normalize paired task-base context: {relative}"
        ) from exc
    object_id = process.stdout.decode("ascii").strip()
    return object_id, _git_blob(root, object_id)


def _assert_index_snapshot_files(root: Path, files: list[dict[str, Any]]) -> None:
    """Prove ignored context is represented exactly in the synthetic base index."""
    for item in files:
        result = _git(
            root,
            "--literal-pathspecs",
            "ls-files",
            "--stage",
            "-z",
            "--",
            item["path"],
        ).stdout
        entries = [value for value in result.split("\0") if value]
        if len(entries) != 1 or "\t" not in entries[0]:
            raise types.EvaluationError(
                f"paired task-base did not index context exactly once: {item['path']}"
            )
        metadata, indexed_path = entries[0].split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3 or indexed_path.replace("\\", "/") != item["path"]:
            raise types.EvaluationError(
                f"paired task-base indexed an unexpected context path: {item['path']}"
            )
        expected_mode = "100755" if item["mode"] & 0o111 else "100644"
        if fields[0] != expected_mode or fields[2] != "0":
            raise types.EvaluationError(
                f"paired task-base context mode differs from its snapshot: {item['path']}"
            )
        expected_object, expected_data = _git_blob_for_worktree_bytes(
            root, item["path"], item["data"]
        )
        if fields[1] != expected_object or _git_blob(root, fields[1]) != expected_data:
            raise types.EvaluationError(
                f"paired task-base context bytes differ from its snapshot: {item['path']}"
            )


def _assert_task_base_snapshot_files(
    root: Path,
    task_base_ref: str,
    files: list[dict[str, Any]],
    *,
    verify_worktree_snapshot: bool = True,
) -> None:
    """Verify that every explicit context file remains measurable from the task base."""
    for item in files:
        result = _git(
            root,
            "--literal-pathspecs",
            "ls-tree",
            "-z",
            task_base_ref,
            "--",
            item["path"],
        ).stdout
        entries = [value for value in result.split("\0") if value]
        if len(entries) != 1 or "\t" not in entries[0]:
            raise types.EvaluationError(
                f"paired task-base does not retain measurable context: {item['path']}"
            )
        metadata, tree_path = entries[0].split("\t", 1)
        fields = metadata.split()
        expected_mode = "100755" if item["mode"] & 0o111 else "100644"
        if (
            len(fields) != 3
            or fields[0] != expected_mode
            or fields[1] != "blob"
            or tree_path.replace("\\", "/") != item["path"]
        ):
            raise types.EvaluationError(
                f"paired task-base context identity is invalid: {item['path']}"
            )
        tree_data = _git_blob(root, fields[2])
        if not verify_worktree_snapshot:
            continue
        expected_object, expected_data = _git_blob_for_worktree_bytes(
            root, item["path"], item["data"]
        )
        if fields[2] != expected_object or tree_data != expected_data:
            raise types.EvaluationError(
                f"paired task-base context blob is invalid: {item['path']}"
            )


def _prepare_task_base(
    root: Path,
    original_commit: str,
    force_files: list[dict[str, Any]] | None = None,
) -> str:
    """Create a clean synthetic commit for one disposable evaluation arm."""
    _git(root, "add", "-A")
    force_files = force_files or []
    if force_files:
        _git(
            root,
            "--literal-pathspecs",
            "add",
            "-f",
            "--",
            *(item["path"] for item in force_files),
        )
        _assert_index_snapshot_files(root, force_files)
    tree = _git(root, "write-tree").stdout.strip()
    environment = os.environ.copy()
    environment.update({
        "GIT_AUTHOR_NAME": "Harness Evaluation",
        "GIT_AUTHOR_EMAIL": "harness-evaluation@invalid",
        "GIT_COMMITTER_NAME": "Harness Evaluation",
        "GIT_COMMITTER_EMAIL": "harness-evaluation@invalid",
        "GIT_AUTHOR_DATE": "946684800 +0000",
        "GIT_COMMITTER_DATE": "946684800 +0000",
    })
    try:
        process = subprocess.run(
            ["git", "-C", str(root.resolve()), "commit-tree", tree, "-p", original_commit],
            check=True,
            input="Harness evaluation pre-task state\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise types.EvaluationError("could not create the arm pre-task commit") from exc
    task_base_ref = process.stdout.strip()
    # The index already matches the new tree. A soft reset advances HEAD without
    # re-checking files through platform line-ending conversion.
    _git(root, "reset", "--soft", task_base_ref)
    if _git(root, "rev-parse", "HEAD").stdout.strip() != task_base_ref:
        raise types.EvaluationError("arm pre-task commit was not installed as HEAD")
    if _git(root, "status", "--porcelain").stdout.strip():
        raise types.EvaluationError("paired worktree is not clean at task start")
    _assert_task_base_snapshot_files(root, task_base_ref, force_files)
    return task_base_ref


def _paired_arm_orders(repetitions: int, order: str, seed: int) -> list[list[str]]:
    if repetitions < 1:
        raise types.EvaluationError("paired-run repetitions must be at least 1")
    result: list[list[str]] = []
    randomizer = random.Random(seed)
    for index in range(repetitions):
        if order == "randomized":
            arms = ["baseline", "harness"]
            randomizer.shuffle(arms)
        elif order == "counterbalanced":
            arms = ["baseline", "harness"] if index % 2 == 0 else ["harness", "baseline"]
        elif order == "baseline-first":
            arms = ["baseline", "harness"]
        elif order == "harness-first":
            arms = ["harness", "baseline"]
        else:
            raise types.EvaluationError("paired-run order policy is invalid")
        result.append(arms)
    return result


def _assert_clean_codex_home(path: Path) -> None:
    if not path.is_dir():
        raise types.EvaluationError("paired-run requires an existing dedicated CODEX_HOME")
    forbidden = (
        path / "AGENTS.md",
        path / "AGENTS.override.md",
        path / "config.toml",
        path / "skills" / "harness",
    )
    existing = [str(item.name) for item in forbidden if item.exists()]
    if existing:
        raise types.EvaluationError(f"dedicated CODEX_HOME contains comparison-changing files: {', '.join(existing)}")


def _known_skill_isolation_gaps(
    *,
    codex_home: Path,
    user_home: Path,
    admin_skills_root: Path | None = None,
) -> list[str]:
    gaps: list[str] = []
    if (user_home / ".agents" / "skills" / "harness").exists():
        gaps.append("user-harness-skill")
    if (user_home / ".codex" / "skills" / "harness").exists():
        gaps.append("legacy-user-harness-skill")
    if (codex_home / "skills" / "harness").exists():
        gaps.append("codex-home-harness-skill")
    selected_admin_root = admin_skills_root
    if selected_admin_root is None and os.name != "nt":
        selected_admin_root = Path("/etc/codex/skills")
    if selected_admin_root is not None and (selected_admin_root / "harness").exists():
        gaps.append("admin-harness-skill")
    return sorted(set(gaps))


def _windows_cleanup_receipt(path_text: str | None) -> bool:
    if os.name != "nt":
        return True
    if not path_text:
        return False
    try:
        value = types.load_json(Path(path_text))
    except types.EvaluationError:
        return False
    return value == {
        "schemaVersion": 1,
        "platform": "windows",
        "implementationSha256": capture.windows_cleanup_implementation_sha256(),
        "verified": True,
    }


def _paired_arm(
    *,
    evaluation_store: store_module.EvaluationStore,
    repository_id: str,
    root: Path,
    prompt_bytes: bytes,
    args: argparse.Namespace,
    arm: str,
    order: str,
    comparison_id: str,
    pair_id: str,
    verification: dict[str, Any],
    verification_digest: str,
    user_home: Path,
    windows_cleanup_verified: bool,
    task_stratum: dict[str, Any],
    patch_scope_profile: dict[str, Any] | None,
    source_snapshot_id: str,
    task_base_ref: str,
    task_context_files: list[dict[str, Any]],
    materialization_isolation_gaps: list[str],
) -> dict[str, Any]:
    record = _new_record(
        evaluation_store=evaluation_store,
        root=root,
        repository_id=repository_id,
        prompt=prompt_bytes,
        capture_mode="runtime-instrumented",
        args=args,
        arm=arm,
        comparison_id=comparison_id,
        pair_id=pair_id,
        arm_order=order,
        source_snapshot_id_override=source_snapshot_id,
    )
    isolation_gaps = _known_skill_isolation_gaps(
        codex_home=Path(args.codex_home), user_home=user_home
    )
    if not windows_cleanup_verified:
        isolation_gaps.append("windows-process-tree-unverified")
    isolation_gaps.extend(materialization_isolation_gaps)
    record["comparison"]["isolationGaps"] = sorted(set(isolation_gaps))
    record["comparison"]["isolationStatus"] = (
        "complete" if not record["comparison"]["isolationGaps"] else "partial"
    )
    record["task"]["category"] = task_stratum["category"]
    record["task"]["complexity"]["level"] = task_stratum["complexityLevel"]
    record["task"]["impact"]["level"] = task_stratum["impactLevel"]
    record["task"]["uncertainty"]["level"] = task_stratum["uncertaintyLevel"]
    evaluation_store.create_pending(record)
    summary, exit_code, elapsed_ms, cleanup_verified, version = capture.run_codex_jsonl(
        repository=root,
        prompt=prompt_bytes.decode("utf-8"),
        sandbox=args.sandbox,
        timeout_seconds=args.timeout,
        codex_binary=args.codex_binary,
        codex_home=Path(args.codex_home),
        user_home=user_home,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    completed = capture.apply_capture_to_record(
        record,
        summary=summary,
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        cleanup_verified=cleanup_verified,
        codex_version=version,
        ended_at=types.timestamp_text(evaluation_store.clock.now_utc()),
    )
    _assert_task_base_snapshot_files(
        root,
        task_base_ref,
        task_context_files,
        verify_worktree_snapshot=False,
    )
    task_fingerprint = _result_fingerprint(
        evaluation_store, root, base_ref=task_base_ref
    )
    _set_result_fingerprint(
        completed,
        task_fingerprint,
    )
    if patch_scope_profile is not None:
        completed["result"]["patchScope"] = harness_patch_scope.evaluate(
            root=root,
            profile=patch_scope_profile,
            repository_id=repository_id,
            store=evaluation_store,
            base_ref=task_base_ref,
        )
    check_ref = evaluation_store.pseudonym(repository_id, "check", verification["id"])
    pre_verification_signature = _repository_state_signature(
        evaluation_store, root, base_ref=task_base_ref
    )
    verification_result, verification_cleanup_verified = _run_verification(
        root=root,
        profile=verification,
        profile_digest=verification_digest,
        check_ref=check_ref,
    )
    completed["outcome"]["verification"] = [verification_result]
    completed["outcome"]["criticalFailure"] = completed["outcome"]["criticalFailure"] or verification_result["result"] == "failed"
    completed["result"]["verificationProfileFingerprint"] = verification_digest
    first_post_verification_signature = _repository_state_signature(
        evaluation_store, root, base_ref=task_base_ref
    )
    time.sleep(VERIFICATION_QUIESCENCE_SECONDS)
    post_verification_signature = _repository_state_signature(
        evaluation_store, root, base_ref=task_base_ref
    )
    _record_verification_repository_state(
        completed,
        pre_verification_signature=pre_verification_signature,
        post_verification_signature=post_verification_signature,
        quiescent=(
            None
            if first_post_verification_signature is None
            or post_verification_signature is None
            else first_post_verification_signature == post_verification_signature
        ),
    )
    if not verification_cleanup_verified:
        completed["comparison"]["isolationStatus"] = "failed"
        completed["comparison"]["isolationGaps"] = sorted(set(
            completed["comparison"]["isolationGaps"]
            + ["verification-process-cleanup"]
        ))
    if not cleanup_verified:
        completed["comparison"]["isolationStatus"] = "failed"
        completed["comparison"]["isolationGaps"] = sorted(set(
            completed["comparison"]["isolationGaps"] + ["process-cleanup"]
        ))
    evaluation_store.complete_run(completed)
    return types.seal_record(completed)


def command_paired_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.validate_materialization and not args.dry_run:
        raise types.EvaluationError("--validate-materialization requires --dry-run")
    if _git(root, "status", "--porcelain").stdout.strip():
        raise types.EvaluationError("paired-run requires a clean Git repository")
    prompt_bytes = _prompt_bytes(args)
    plan = types.load_json(Path(args.comparison_plan))
    types.validate_comparison_plan(plan)
    verification = _verification_profile(Path(args.verification))
    verification_digest = types.digest_bytes(types.canonical_bytes(verification))
    if plan["verificationProfileFingerprint"] not in {None, verification_digest}:
        raise types.EvaluationError("comparison plan verification fingerprint does not match the profile")
    patch_scope_profile = None
    if args.patch_scope_profile:
        patch_scope_profile = harness_patch_scope.validate_profile(
            types.load_json(Path(args.patch_scope_profile))
        )
    patch_scope_digest = (
        types.digest_bytes(types.canonical_bytes(patch_scope_profile))
        if patch_scope_profile is not None else None
    )
    if plan["patchScopeProfileFingerprint"] != patch_scope_digest:
        raise types.EvaluationError("comparison plan patch-scope fingerprint does not match the profile")
    codex_home = Path(args.codex_home).resolve()
    _assert_clean_codex_home(codex_home)
    windows_cleanup_verified = _windows_cleanup_receipt(args.windows_cleanup_receipt)
    admin_isolation_gaps = _known_skill_isolation_gaps(
        codex_home=codex_home,
        user_home=Path(tempfile.gettempdir()) / "harness-nonexistent-isolated-home",
    )
    commit = _git(root, "rev-parse", "HEAD").stdout.strip()
    harness_snapshot = _capture_local_harness_snapshot(root, commit)
    task_context_files = [
        *harness_snapshot["evidenceFiles"],
        *harness_snapshot["projectContextFiles"],
    ]
    materialization_report = {
        "mode": PAIRED_MATERIALIZATION_MODE,
        "sourceWorktreeCount": harness_snapshot["worktreeCount"],
        "managedFileCount": len(harness_snapshot["managedFiles"]),
        "evidenceFileCount": len(harness_snapshot["evidenceFiles"]),
        "projectContextFileCount": len(harness_snapshot["projectContextFiles"]),
        "projectConfigPresent": harness_snapshot["projectConfigPresent"],
        "projectConfigMaterialized": False,
        "effectiveProjectConfigLoad": (
            "unverified" if harness_snapshot["projectConfigPresent"] else "not-applicable"
        ),
        "projectAgentConfigCount": harness_snapshot["projectAgentConfigCount"],
        "effectiveProjectAgentLoad": (
            "unverified"
            if harness_snapshot["projectAgentConfigCount"]
            else "not-applicable"
        ),
        "projectAgentDependenciesVerified": harness_snapshot[
            "projectAgentDependenciesVerified"
        ],
        "projectRules": "intentionally-disabled",
        "projectHooks": "not-enabled-by-harness",
        "sourceManifestSha256": harness_snapshot["sourceManifestSha256"],
        "treatmentManifestSha256": harness_snapshot["treatmentManifestSha256"],
        "overlaySha256": harness_snapshot["overlaySha256"],
        "clonePerformed": False,
        "materializationValidated": False,
        "expectedGitRemoteRetained": False,
        "observedGitRemoteRetained": None,
    }
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    arm_orders = _paired_arm_orders(args.repetitions, args.order, seed)
    if args.dry_run:
        materialization_gaps: list[str] = list(harness_snapshot["isolationGaps"])
        if args.validate_materialization:
            with tempfile.TemporaryDirectory(prefix="harness-materialization-") as directory:
                pair_root = Path(directory).resolve()
                baseline_root = pair_root / "baseline"
                treatment_root = pair_root / "treatment"
                _verify_local_harness_snapshot(root, harness_snapshot)
                _clone_local_evaluation_arm(root, baseline_root, commit)
                _clone_local_evaluation_arm(root, treatment_root, commit)
                result = _materialize_paired_arms(
                    baseline_root, treatment_root, harness_snapshot
                )
                baseline_base = _prepare_task_base(
                    baseline_root, commit, task_context_files
                )
                treatment_base = _prepare_task_base(
                    treatment_root, commit, task_context_files
                )
                _assert_evidence_snapshot(baseline_root, harness_snapshot)
                _assert_evidence_snapshot(treatment_root, harness_snapshot)
                _assert_project_context_snapshot(baseline_root, harness_snapshot)
                _assert_project_context_snapshot(treatment_root, harness_snapshot)
                _assert_task_base_snapshot_files(
                    baseline_root, baseline_base, task_context_files
                )
                _assert_task_base_snapshot_files(
                    treatment_root, treatment_base, task_context_files
                )
                materialization_gaps = result["isolationGaps"]
            materialization_report.update(
                {
                    "clonePerformed": True,
                    "materializationValidated": True,
                    "projectConfigMaterialized": harness_snapshot["projectConfigPresent"],
                    "observedGitRemoteRetained": False,
                }
            )
        _print(
            {
                "valid": True,
                "dryRun": True,
                "sourceCommit": commit,
                "armOrders": arm_orders,
                "orderPolicy": args.order,
                "repetitions": args.repetitions,
                "seed": seed,
                "liveCodexInvoked": False,
                "stateWritten": False,
                "isolatedUserHome": True,
                "materialization": materialization_report,
                "windowsCleanupReceiptValid": windows_cleanup_verified,
                "isolationGaps": sorted(set(
                    admin_isolation_gaps
                    + materialization_gaps
                    + ([] if windows_cleanup_verified else ["windows-process-tree-unverified"])
                )),
            }
        )
        return 0

    evaluation_store = _store(args)
    repository_id = evaluation_store.register_repository(root)
    comparison_records: list[dict[str, Any]] = []
    materialization_report.update(
        {
            "clonePerformed": True,
            "materializationValidated": True,
            "projectConfigMaterialized": harness_snapshot["projectConfigPresent"],
            "observedGitRemoteRetained": False,
        }
    )
    with tempfile.TemporaryDirectory(prefix="harness-paired-") as directory:
        temporary = Path(directory).resolve()
        for repetition_index, arm_order in enumerate(arm_orders, start=1):
            comparison_id = str(evaluation_store.ids.new_uuid())
            pair_id = str(evaluation_store.ids.new_uuid())
            pair_root = temporary / f"pair-{repetition_index:03d}"
            baseline_root = pair_root / "baseline"
            treatment_root = pair_root / "treatment"
            store_module.ensure_state_outside_repositories(evaluation_store.root, [root, baseline_root, treatment_root])
            _verify_local_harness_snapshot(root, harness_snapshot)
            _clone_local_evaluation_arm(root, baseline_root, commit)
            _clone_local_evaluation_arm(root, treatment_root, commit)
            try:
                materialization = _materialize_paired_arms(
                    baseline_root, treatment_root, harness_snapshot
                )
                task_base_refs = {
                    "baseline": _prepare_task_base(
                        baseline_root, commit, task_context_files
                    ),
                    "harness": _prepare_task_base(
                        treatment_root, commit, task_context_files
                    ),
                }
                _assert_evidence_snapshot(baseline_root, harness_snapshot)
                _assert_evidence_snapshot(treatment_root, harness_snapshot)
                _assert_project_context_snapshot(baseline_root, harness_snapshot)
                _assert_project_context_snapshot(treatment_root, harness_snapshot)
                source_snapshot_id = f"git:{commit}"
                records: dict[str, dict[str, Any]] = {}
                for index, arm in enumerate(arm_order):
                    user_home = pair_root / f"{arm}-user-home"
                    records[arm] = _paired_arm(
                        evaluation_store=evaluation_store,
                        repository_id=repository_id,
                        root=baseline_root if arm == "baseline" else treatment_root,
                        prompt_bytes=prompt_bytes,
                        args=args,
                        arm=arm,
                        order="first" if index == 0 else "second",
                        comparison_id=comparison_id,
                        pair_id=pair_id,
                        verification=verification,
                        verification_digest=verification_digest,
                        user_home=user_home,
                        windows_cleanup_verified=windows_cleanup_verified,
                        task_stratum=plan["taskStratum"],
                        patch_scope_profile=patch_scope_profile,
                        source_snapshot_id=source_snapshot_id,
                        task_base_ref=task_base_refs[arm],
                        task_context_files=task_context_files,
                        materialization_isolation_gaps=materialization["isolationGaps"],
                    )
                comparison_record = compare.compare_runs(
                    baseline=records["baseline"],
                    treatment=records["harness"],
                    plan=plan,
                    comparison_id=comparison_id,
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at=types.timestamp_text(evaluation_store.clock.now_utc()),
                )
                comparison_record["randomizationSeed"] = seed
                if args.order in {"baseline-first", "harness-first"}:
                    comparison_record["confounders"] = sorted(set(comparison_record["confounders"] + ["arm-order"]))
                comparison_record = types.seal_record(comparison_record)
                types.validate_comparison_record(comparison_record)
                evaluation_store.write_auxiliary(repository_id, "comparisons", comparison_id, comparison_record)
                comparison_records.append(comparison_record)
            finally:
                if pair_root.is_dir():
                    shutil.rmtree(pair_root)
    _print(
        {
            "schemaVersion": 1,
            "repositoryId": repository_id,
            "sourceCommit": commit,
            "orderPolicy": args.order,
            "seed": seed,
            "repetitions": args.repetitions,
            "materialization": materialization_report,
            "comparisons": comparison_records,
        }
    )
    return 0


def _validate_probe_suite(suite: Any, *, kind: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    if not isinstance(suite, dict) or suite.get("schemaVersion") != 1:
        raise types.EvaluationError("probe suite must be a schemaVersion 1 object")
    cases = suite.get("cases")
    candidates = suite.get("candidates")
    if not isinstance(cases, list) or not isinstance(candidates, list):
        raise types.EvaluationError("probe suite requires cases and candidates arrays")
    if not candidates or any(not isinstance(value, str) or not value for value in candidates):
        raise types.EvaluationError("probe suite candidates must be non-empty strings")
    if len(candidates) != len(set(candidates)):
        raise types.EvaluationError("probe suite candidates must be unique")
    behavior_tags = suite.get("behaviorTags", [])
    if not isinstance(behavior_tags, list) or any(
        not isinstance(value, str) or not value for value in behavior_tags
    ):
        raise types.EvaluationError("probe suite behaviorTags must be strings")
    if len(behavior_tags) != len(set(behavior_tags)):
        raise types.EvaluationError("probe suite behaviorTags must be unique")
    if kind == "change-discipline" and not behavior_tags:
        raise types.EvaluationError("change-discipline suite requires behaviorTags")
    seen_case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("prompt"), str) or not isinstance(case.get("caseId"), str):
            raise types.EvaluationError("probe case fields are invalid")
        if not case["caseId"] or case["caseId"] in seen_case_ids:
            raise types.EvaluationError("probe caseId values must be non-empty and unique")
        seen_case_ids.add(case["caseId"])
        expected = case.get("expected")
        if not isinstance(expected, dict) or expected.get("selection") not in candidates:
            raise types.EvaluationError("probe expected selection must name a candidate")
        if kind == "change-discipline":
            required = expected.get("requiredBehaviors")
            forbidden = expected.get("forbiddenBehaviors")
            if not isinstance(required, list) or not isinstance(forbidden, list):
                raise types.EvaluationError(
                    "change-discipline expectations require requiredBehaviors and forbiddenBehaviors arrays"
                )
            if any(value not in behavior_tags for value in required + forbidden):
                raise types.EvaluationError("change-discipline expectation uses an unknown behavior tag")
            if len(required) != len(set(required)) or len(forbidden) != len(set(forbidden)):
                raise types.EvaluationError("change-discipline behavior expectations must be unique")
            if set(required) & set(forbidden):
                raise types.EvaluationError("required and forbidden behaviors must be disjoint")
    return cases, candidates, behavior_tags


def _score_probe_case(
    *,
    selected: Any,
    expected: dict[str, Any],
    kind: str,
    behavior_tags: list[str] | None = None,
) -> dict[str, Any]:
    actual_selection = selected.get("selection") if isinstance(selected, dict) else None
    expected_selection = expected["selection"]
    result: dict[str, Any] = {
        "expected": expected_selection,
        "actual": actual_selection,
        "matched": actual_selection == expected_selection,
    }
    if kind == "change-discipline":
        actual_behaviors = selected.get("behaviors") if isinstance(selected, dict) else None
        if not isinstance(actual_behaviors, list) or any(not isinstance(value, str) for value in actual_behaviors):
            actual_behaviors = []
        actual_set = set(actual_behaviors)
        required = expected["requiredBehaviors"]
        forbidden = expected["forbiddenBehaviors"]
        unknown = actual_set - set(behavior_tags or [])
        behaviors_matched = set(required) <= actual_set and not (set(forbidden) & actual_set) and not unknown
        result.update(
            {
                "requiredBehaviors": required,
                "forbiddenBehaviors": forbidden,
                "actualBehaviors": sorted(actual_set),
                "unknownBehaviors": sorted(unknown),
                "behaviorsMatched": behaviors_matched,
                "matched": result["matched"] and behaviors_matched,
            }
        )
    return result


def _probe_suite(args: argparse.Namespace, *, kind: str) -> int:
    suite = types.load_json(Path(args.cases))
    cases, candidates, behavior_tags = _validate_probe_suite(suite, kind=kind)
    if args.validate_only:
        _print(
            {
                "schemaVersion": 1,
                "probeType": f"{kind}-selection-probe",
                "caseCount": len(cases),
                "valid": True,
                "liveCodexInvoked": False,
            }
        )
        return 0
    if not args.root:
        raise types.EvaluationError("provide --root unless --validate-only is used")
    root = Path(args.root).resolve()
    results = []
    for case in cases:
        if kind == "change-discipline":
            instruction = (
                "Classify the following change-discipline case. Return only JSON with keys selection, "
                "ambiguity, and behaviors. The behaviors value must be an array containing only listed tags. "
                f"Candidates: {json.dumps(candidates, ensure_ascii=False)}. "
                f"Behavior tags: {json.dumps(behavior_tags, ensure_ascii=False)}\nCase: {case['prompt']}"
            )
        else:
            instruction = (
                f"Classify the following {kind} selection case. Return only JSON with keys selection and ambiguity. "
                f"Candidates: {json.dumps(candidates, ensure_ascii=False)}\nCase: {case['prompt']}"
            )
        summary, exit_code, _, cleanup, version = capture.run_codex_jsonl(
            repository=root,
            prompt=instruction,
            sandbox="read-only",
            timeout_seconds=args.timeout,
            codex_binary=args.codex_binary,
            codex_home=Path(args.codex_home) if args.codex_home else None,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            capture_final_message=True,
        )
        selected: Any = None
        if summary.final_message:
            try:
                selected = json.loads(summary.final_message)
            except json.JSONDecodeError:
                selected = {"selection": "unknown", "ambiguity": True}
        result = {
            "caseId": case["caseId"],
            **_score_probe_case(
                selected=selected,
                expected=case["expected"],
                kind=kind,
                behavior_tags=behavior_tags,
            ),
            "captureCompleteness": "complete" if summary.terminal_event_observed and summary.parser_compatibility == "supported" else "partial",
            "processExitCode": exit_code,
            "processCleanupVerified": cleanup,
            "codexVersion": version,
        }
        results.append(result)
    matched = sum(item["matched"] for item in results)
    _print(
        {
            "schemaVersion": 1,
            "probeType": f"{kind}-selection-probe",
            "caseCount": len(results),
            "matchedCount": matched,
            "accuracy": matched / len(results) if results else None,
            "results": results,
            "rawPromptsStored": False,
        }
    )
    return 0


def command_skill_suite(args: argparse.Namespace) -> int:
    return _probe_suite(args, kind="skill")


def command_route_suite(args: argparse.Namespace) -> int:
    return _probe_suite(args, kind="route")


def command_change_discipline_suite(args: argparse.Namespace) -> int:
    return _probe_suite(args, kind="change-discipline")


def _add_state_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-home", help="Override the user-local Harness evaluation state root")


def _add_runtime(parser: argparse.ArgumentParser, *, require_codex_home: bool = False) -> None:
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--codex-home", required=require_codex_home)
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", type=types.reasoning_effort, default="unknown")
    parser.add_argument("--timeout", type=float, default=900.0)


def _add_task_source(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-file")
    group.add_argument("--task-stdin", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run one opt-in instrumented Codex task")
    run.add_argument("--root", required=True)
    _add_task_source(run)
    run.add_argument("--arm", choices=sorted(types.ARMS), default="unpaired")
    run.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    run.add_argument("--category", choices=sorted(types.TASK_CATEGORIES), default="unknown")
    run.add_argument("--classification-source", choices=sorted(types.CLASSIFICATION_SOURCES), default="user")
    run.add_argument("--execution-class", choices=sorted(types.EXECUTION_CLASSES), default="unknown")
    run.add_argument("--patch-scope-profile")
    _add_runtime(run)
    _add_state_home(run)
    run.set_defaults(handler=command_run)

    start = subparsers.add_parser("record-start", help="Start a manual or agent-reported record")
    start.add_argument("--root", required=True)
    start.add_argument("--capture", choices=("manual", "agent-reported"), default="manual")
    start.add_argument("--category", choices=sorted(types.TASK_CATEGORIES), default="unknown")
    start.add_argument("--classification-source", choices=sorted(types.CLASSIFICATION_SOURCES), default="user")
    start.set_defaults(sandbox="unknown", reasoning_effort="unknown", execution_class="unknown", model=None)
    _add_state_home(start)
    start.set_defaults(handler=command_record_start)

    complete = subparsers.add_parser("record-complete", help="Complete a pending manual record")
    complete.add_argument("--run", required=True)
    complete.add_argument("--completion", choices=sorted(types.COMPLETION_STATES - {"unknown"}), required=True)
    complete.add_argument("--report", help="Optional structured observation report to add after completion")
    _add_state_home(complete)
    complete.set_defaults(handler=command_record_complete)

    annotate = subparsers.add_parser("annotate", help="Add immutable user outcome metadata")
    annotate.add_argument("--run", required=True)
    annotate.add_argument("--acceptance", choices=("accepted", "accepted-with-corrections", "rejected", "unknown"), required=True)
    annotate.add_argument("--corrections", type=int)
    annotate.add_argument("--reopened", action="store_true")
    annotate.add_argument("--supersedes", help="Active Annotation Schema 1 or 2 record to replace")
    _add_state_home(annotate)
    annotate.set_defaults(handler=command_annotate)

    list_parser = subparsers.add_parser("list", help="List local run metadata")
    list_parser.add_argument("--repository")
    _add_state_home(list_parser)
    list_parser.set_defaults(handler=command_list)

    inspect = subparsers.add_parser("inspect", help="Inspect one validated run record")
    inspect.add_argument("--run", required=True)
    _add_state_home(inspect)
    inspect.set_defaults(handler=command_inspect)

    observation = subparsers.add_parser("add-observation", help="Add an immutable structured observation")
    observation.add_argument("--run", required=True)
    observation.add_argument("--kind", choices=("supplement", "replacement", "withdrawal"), default="supplement")
    observation.add_argument("--report")
    observation.add_argument("--supersedes")
    _add_state_home(observation)
    observation.set_defaults(handler=command_add_observation)

    view = subparsers.add_parser("view", help="Compute a non-persistent derived evaluation view")
    view.add_argument("--run", required=True)
    _add_state_home(view)
    view.set_defaults(handler=command_view)

    inspect_observation = subparsers.add_parser(
        "inspect-observation", help="Inspect an active or inactive observation record"
    )
    inspect_observation.add_argument("--observation", required=True)
    _add_state_home(inspect_observation)
    inspect_observation.set_defaults(handler=command_inspect_observation)

    export = subparsers.add_parser("export", help="Export redacted records")
    export.add_argument("--repository", required=True)
    export.add_argument("--output")
    _add_state_home(export)
    export.set_defaults(handler=command_export)

    purge = subparsers.add_parser("purge", help="Purge completed local evaluation records")
    purge.add_argument("--repository", required=True)
    _add_state_home(purge)
    purge.set_defaults(handler=command_purge)

    repair = subparsers.add_parser("repair", help="Inspect or quarantine corrupt records")
    repair.add_argument("--repository", required=True)
    repair.add_argument("--quarantine", action="store_true")
    _add_state_home(repair)
    repair.set_defaults(handler=command_repair)

    comparison = subparsers.add_parser("compare", help="Compare two completed run records")
    comparison.add_argument("--baseline-run", required=True)
    comparison.add_argument("--treatment-run", required=True)
    comparison.add_argument("--plan", required=True)
    _add_state_home(comparison)
    comparison.set_defaults(handler=command_compare)

    proposal = subparsers.add_parser("propose", help="Create a non-binding evidence proposal")
    proposal.add_argument("--repository", required=True)
    proposal.add_argument(
        "--comparison-plan",
        help="Optional Schema 2 plan required for concrete configuration attribution",
    )
    proposal.add_argument("--category", choices=sorted(types.TASK_CATEGORIES), default="unknown")
    proposal.add_argument("--complexity", choices=sorted(types.LEVELS), default="unknown")
    proposal.add_argument("--impact", choices=sorted(types.LEVELS), default="unknown")
    proposal.add_argument(
        "--evaluation-stratum",
        help="Restrict proposal evidence to one evaluation-stratum SHA-256 fingerprint",
    )
    proposal.add_argument(
        "--report-envelope",
        action="store_true",
        help="Wrap the sealed proposal with non-persistent warnings and exclusion references",
    )
    _add_state_home(proposal)
    proposal.set_defaults(handler=command_propose)

    paired = subparsers.add_parser("paired-run", help="Run an isolated with/without-Harness comparison")
    paired.add_argument("--root", required=True)
    _add_task_source(paired)
    paired.add_argument("--comparison-plan", required=True)
    paired.add_argument("--verification", required=True)
    paired.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="workspace-write")
    paired.add_argument("--category", choices=sorted(types.TASK_CATEGORIES), default="unknown")
    paired.add_argument("--classification-source", choices=sorted(types.CLASSIFICATION_SOURCES), default="fixture")
    paired.add_argument("--execution-class", choices=sorted(types.EXECUTION_CLASSES), default="unknown")
    paired.add_argument("--seed", type=int)
    paired.add_argument("--repetitions", type=int, default=1)
    paired.add_argument(
        "--order",
        choices=("randomized", "counterbalanced", "baseline-first", "harness-first"),
        default="randomized",
    )
    paired.add_argument("--dry-run", action="store_true")
    paired.add_argument(
        "--validate-materialization",
        action="store_true",
        help="With --dry-run, create disposable clones and validate paired materialization",
    )
    paired.add_argument("--patch-scope-profile")
    paired.add_argument(
        "--windows-cleanup-receipt",
        help="User-local receipt proving this Windows cleanup implementation",
    )
    _add_runtime(paired, require_codex_home=True)
    _add_state_home(paired)
    paired.set_defaults(handler=command_paired_run)

    for name, handler in (
        ("skill-selection-suite", command_skill_suite),
        ("route-selection-suite", command_route_suite),
        ("change-discipline-suite", command_change_discipline_suite),
    ):
        suite = subparsers.add_parser(name)
        suite.add_argument("--root")
        suite.add_argument("--cases", required=True)
        suite.add_argument("--validate-only", action="store_true")
        _add_runtime(suite)
        suite.set_defaults(handler=handler)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (types.EvaluationError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
