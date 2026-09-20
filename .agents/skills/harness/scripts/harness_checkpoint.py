#!/usr/bin/env python3
"""Opt-in, bounded task checkpoints. Native Codex owns agents and conversations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time

from harness_eval_lock import FileLock

MAX_BYTES = 128 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
ACTIVE = {"running", "stop-requested"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def checked(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink() or part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Checkpoint paths must not contain links or reparse points")
    return path


def read_json(path):
    path = checked(path)
    if path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("Checkpoint JSON exceeds the 4 MiB limit")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate checkpoint JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Use a bounded lowercase task/run identifier")
    return value


def file_snapshot(root, names, budget, cache):
    if not isinstance(names, list) or len(names) > 64 or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise ValueError("Checkpoint paths must be a unique list of at most 64 files")
    result = {}
    for name in names:
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or PurePosixPath(name).is_absolute() or any(p in {"", ".", ".."} for p in name.split("/"))):
            raise ValueError("Use exact project-relative POSIX file paths without traversal")
        path = checked(root / name)
        if not path.is_relative_to(root):
            raise ValueError("Checkpoint file escaped project")
        key = digest(name.casefold())
        if key in result:
            raise ValueError("Case-colliding checkpoint paths")
        if name in cache:
            result[key] = cache[name]
            continue
        if not path.exists():
            result[key] = None
            continue
        if not path.is_file():
            raise ValueError("Declare individual files; directory hashing is not supported")
        before = path.stat()
        budget[0] += before.st_size
        if budget[0] > MAX_BYTES:
            raise ValueError("Checkpoint file budget exceeded; use explicit content-addressed metadata for large data")
        value = hashlib.sha256()
        with path.open("rb") as stream:
            read = 0
            while chunk := stream.read(1024 * 1024):
                read += len(chunk)
                if read > before.st_size:
                    raise ValueError("Checkpoint input changed while hashing")
                value.update(chunk)
        after = checked(path).stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Checkpoint input changed while hashing")
        result[key] = value.hexdigest()
        cache[name] = result[key]
    return result


def compile_plan(root, plan):
    if not isinstance(plan, dict) or set(plan) != {"schemaVersion", "tasks"} or type(plan["schemaVersion"]) is not int or plan["schemaVersion"] != 1:
        raise ValueError("Unsupported checkpoint contract")
    if not isinstance(plan["tasks"], list) or not 1 <= len(plan["tasks"]) <= 32:
        raise ValueError("Declare between 1 and 32 checkpoint tasks")
    tasks, names, budget, cache = {}, {}, [0], {}
    for item in plan["tasks"]:
        required = {"id", "dependsOn", "inputs", "outputs", "context", "checks"}
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("Invalid checkpoint task fields")
        name = identifier(item["id"])
        key = digest(name)
        if key in tasks:
            raise ValueError("Duplicate task identifier")
        deps = item["dependsOn"]
        if not isinstance(deps, list) or len(deps) > 32 or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError("Invalid task dependencies")
        context = item["context"]
        if not isinstance(context, dict) or len(context) > 32 or any(not isinstance(k, str) or not ID.fullmatch(k) or not isinstance(v, str) or not HASH.fullmatch(v) for k, v in context.items()):
            raise ValueError("Context contains named SHA-256 identities, not raw environment or task text")
        checks = item["checks"]
        if not isinstance(checks, list) or not 1 <= len(checks) <= 8:
            raise ValueError("Each task needs 1-8 actual verification commands")
        for command in checks:
            if (not isinstance(command, list) or not 1 <= len(command) <= 32
                    or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command)
                    or sum(len(arg) for arg in command) > 8192):
                raise ValueError("Verification requires bounded argv arrays without shell expansion")
        inputs = file_snapshot(root, item["inputs"], budget, cache)
        outputs = file_snapshot(root, item["outputs"], budget, cache)
        if set(inputs) & set(outputs):
            raise ValueError("Immutable inputs cannot also be task outputs")
        tasks[key] = {"contract": digest(item), "dependencies": [digest(identifier(d)) for d in deps],
                      "inputs": inputs, "outputs": outputs}
        names[key] = name
    ordered, visiting = [], set()
    def visit(key):
        if key not in tasks or key in visiting:
            raise ValueError("Missing dependency or dependency cycle")
        if key in ordered:
            return
        visiting.add(key)
        for dependency in tasks[key]["dependencies"]:
            visit(dependency)
        visiting.remove(key)
        ordered.append(key)
    for key in tasks:
        visit(key)
    return {key: tasks[key] for key in ordered}, names


def reusable(tasks, previous):
    accepted, reasons = set(), {}
    for key, task in tasks.items():
        old = previous.get(key, {})
        reason = []
        if old.get("status") != "completed" or old.get("verification") != "passed":
            reason.append("not-verified")
        if old.get("lifecycle") in ACTIVE:
            reason.append("agent-not-quiescent")
        for field in ("contract", "inputs", "outputs"):
            if old.get(field) != task[field]:
                reason.append(field + "-changed")
        if any(value is None for value in task["inputs"].values()) or any(value is None for value in task["outputs"].values()):
            reason.append("missing-file")
        if any(dependency not in accepted for dependency in task["dependencies"]):
            reason.append("dependency-changed")
        if reason:
            reasons[key] = reason
        else:
            accepted.add(key)
    return accepted, reasons


def save(path, state):
    state["integrity"] = digest({key: value for key, value in state.items() if key != "integrity"})
    payload = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_STATE_BYTES:
        raise ValueError("Checkpoint store exceeds its size budget")
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        checked(path)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def operate(root, store, plan, action, run, *, task=None, previous=None, keep_days=None, observed=None, timeout=60):
    root, store = checked(root), checked(store)
    if not root.is_dir() or store.is_relative_to(root) or root.is_relative_to(store):
        raise ValueError("Use a dedicated user-local checkpoint store outside the project")
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError("Verification timeout must be 1-300 seconds")
    run_key = digest(identifier(run))
    task_key = digest(identifier(task)) if task is not None else None
    tasks, names = ({}, {}) if action in {"quiesce", "remove"} else compile_plan(root, plan)
    if action in {"init", "resume"} and (type(keep_days) is not int or not 1 <= keep_days <= 30):
        raise ValueError("Opt in explicitly with --keep-days 1..30")
    if action not in {"init", "resume"} and not store.is_dir():
        raise ValueError("No checkpoint store exists")
    store.mkdir(parents=True, exist_ok=True)
    path = checked(store / "checkpoint.json")
    with FileLock(checked(store / ".lock")):
        if path.exists():
            state = read_json(path)
            if not isinstance(state, dict) or state.get("integrity") != digest({key: value for key, value in state.items() if key != "integrity"}):
                raise ValueError("Checkpoint integrity mismatch; preserve the file for review")
        else:
            state = {"schemaVersion": 1, "project": digest(str(root)), "runs": {}, "integrity": None}
        if (set(state) != {"schemaVersion", "project", "runs", "integrity"}
                or type(state["schemaVersion"]) is not int or state["schemaVersion"] != 1
                or state["project"] != digest(str(root)) or not isinstance(state["runs"], dict)):
            raise ValueError("Unsupported checkpoint store or different project")
        now = time.time()
        runs = state["runs"]
        if action in {"init", "resume"}:
            if run_key in runs or len(runs) >= 64:
                raise ValueError("Run already exists or the 64-run budget is full; explicitly remove old runs")
            accepted, reasons = set(), {}
            if action == "resume":
                old = runs.get(digest(identifier(previous)))
                if old is None or old["expiresAt"] <= now:
                    raise ValueError("Previous checkpoint is missing or expired")
                if any(t["lifecycle"] in ACTIVE for t in old["tasks"].values()):
                    raise ValueError("Confirm old agents are idle/stopped before resuming")
                accepted, reasons = reusable(tasks, old["tasks"])
            entries = {}
            for key, item in tasks.items():
                entries[key] = {**item, "status": "completed" if key in accepted else "pending",
                                "verification": "passed" if key in accepted else "not-run",
                                "lifecycle": "idle", "attempts": 0}
            runs[run_key] = {"createdAt": now, "expiresAt": now + keep_days * 86400, "tasks": entries}
            save(path, state)
            return {"run": run, "reused": [names[k] for k in tasks if k in accepted],
                    "pending": {names[k]: reasons.get(k, ["new-task"]) for k in tasks if k not in accepted}}
        current = runs.get(run_key)
        if current is None:
            raise ValueError("Unknown checkpoint run")
        if action == "remove":
            if any(t["lifecycle"] in ACTIVE for t in current["tasks"].values()):
                raise ValueError("Cannot remove a run with active or stop-requested agents")
            del runs[run_key]
            save(path, state)
            return {"removed": run}
        if action == "quiesce":
            if observed not in {"idle", "stopped", "closed", "stop-requested"} or task_key not in current["tasks"]:
                raise ValueError("Provide an observed native lifecycle state and existing task")
            current["tasks"][task_key]["lifecycle"] = observed
            save(path, state)
            return {"task": task, "lifecycle": observed, "evidence": "caller-observed"}
        if current["expiresAt"] <= now:
            raise ValueError("Checkpoint expired; quiesce/remove it or start a new run")
        accepted, reasons = reusable(tasks, current["tasks"])
        if action == "status":
            return {"run": run, "complete": len(accepted) == len(tasks)
                    and not any(t["lifecycle"] in ACTIVE for t in current["tasks"].values()),
                    "reusable": [names[k] for k in tasks if k in accepted],
                    "pending": {names[k]: v for k, v in reasons.items()},
                    "nativeLifecycle": "caller-observed", "expiresAt": current["expiresAt"]}
        if task_key not in tasks or task_key not in current["tasks"]:
            raise ValueError("Task is not in this run; resume with a replacement contract")
        entry, actual = current["tasks"][task_key], tasks[task_key]
        if entry["contract"] != actual["contract"] or entry["inputs"] != actual["inputs"]:
            raise ValueError("Task inputs or contract changed; resume into a new run")
        if any(value is None for value in actual["inputs"].values()):
            raise ValueError("A required input is missing")
        if any(dependency not in accepted for dependency in actual["dependencies"]):
            raise ValueError("A dependency is not currently verified")
        if action == "start":
            if entry["status"] == "completed" or entry["lifecycle"] in ACTIVE or entry["attempts"] >= 3:
                raise ValueError("Task is completed, active, or its retry budget is exhausted")
            active = [t for r in runs.values() for t in r["tasks"].values() if t["lifecycle"] in ACTIVE]
            if len(active) >= 8 or actual["outputs"] and any(t["outputs"] for t in active):
                raise ValueError("Checkpoint capacity or single-writer ownership is occupied")
            entry.update(status="running", lifecycle="running", attempts=entry["attempts"] + 1, verification="not-run")
        elif action == "record":
            if entry["status"] != "running" or entry["lifecycle"] != "running":
                raise ValueError("Only a running task can record a result")
            commands = next(item["checks"] for item in plan["tasks"] if item["id"] == task)
            results = []
            deadline = time.monotonic() + timeout
            for command in commands:
                if time.monotonic() >= deadline:
                    results.append(False)
                    break
                try:
                    outcome = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=max(0.01, deadline - time.monotonic()))
                    results.append(outcome.returncode == 0)
                except (OSError, subprocess.TimeoutExpired):
                    results.append(False)
                if not results[-1]:
                    break
            after, _ = compile_plan(root, plan)
            accepted_after, _ = reusable(after, current["tasks"])
            passed = (all(results) and after[task_key]["inputs"] == actual["inputs"]
                      and after[task_key]["outputs"] == actual["outputs"]
                      and all(value is not None for value in after[task_key]["outputs"].values())
                      and all(dep in accepted_after for dep in actual["dependencies"]))
            entry.update(status="completed" if passed else "blocked", verification="passed" if passed else "failed",
                         outputs=after[task_key]["outputs"])
        else:
            raise ValueError("Unknown checkpoint action")
        save(path, state)
        return {"task": task, "status": entry["status"], "verification": entry["verification"],
                "lifecycle": entry["lifecycle"], "attempts": entry["attempts"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "record", "quiesce", "resume", "status", "remove"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--plan", type=Path, help="Required except for quiesce/remove")
    parser.add_argument("--run", required=True)
    parser.add_argument("--task")
    parser.add_argument("--previous")
    parser.add_argument("--keep-days", type=int)
    parser.add_argument("--observed", choices=("idle", "stopped", "closed", "stop-requested"))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        result = operate(args.root, args.store, read_json(args.plan) if args.plan else None, args.action, args.run, task=args.task,
            previous=args.previous, keep_days=args.keep_days, observed=args.observed, timeout=args.timeout)
        print(json.dumps(result, indent=2))
        return 1 if result.get("verification") == "failed" else 0
    except (ValueError, OSError, TimeoutError) as error:
        parser.exit(1, f"checkpoint: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
