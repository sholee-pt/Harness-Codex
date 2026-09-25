#!/usr/bin/env python3
"""Privacy-conscious local state store for Harness evaluation records."""

from __future__ import annotations

import hmac
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import harness_eval_types as types
import harness_eval_view as evaluation_view
import harness_state
from harness_eval_lock import FileLock


REPOSITORY_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class StoreError(types.EvaluationError):
    pass


def default_state_root(environment: dict[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    explicit = env.get("HARNESS_STATE_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    system = platform.system().lower()
    if system == "windows":
        base = env.get("LOCALAPPDATA")
        if not base:
            raise StoreError("LOCALAPPDATA is unavailable; set HARNESS_STATE_HOME explicitly")
        return (Path(base) / "Harness").resolve()
    if system == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Harness").resolve()
    base = env.get("XDG_STATE_HOME")
    if base:
        return (Path(base) / "harness").resolve()
    try:
        return (Path.home() / ".local" / "state" / "harness").resolve()
    except RuntimeError as exc:
        raise StoreError("user state directory is unavailable; set HARNESS_STATE_HOME") from exc


def _contains(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(parent)), os.path.normcase(str(child))]) == os.path.normcase(str(parent))
    except ValueError:
        return False


def ensure_state_outside_repositories(state_root: Path, repositories: Iterable[Path]) -> None:
    resolved_state = state_root.resolve()
    for repository in repositories:
        resolved_repository = repository.resolve()
        if _contains(resolved_repository, resolved_state) or _contains(resolved_state, resolved_repository):
            raise StoreError("evaluation state root and repository/worktree must not contain one another")


def canonical_repository_root(root: Path) -> str:
    resolved = root.resolve()
    try:
        process = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        resolved = Path(process.stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    normalized = os.path.normcase(os.path.normpath(str(resolved)))
    if os.name == "nt":
        normalized = normalized.replace("/", "\\")
    return normalized


def _atomic_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    harness_state.atomic_write_text(path, types.canonical_text(value), mode=mode)


def _auxiliary_record_id(kind: str, value: dict[str, Any]) -> str:
    return value["comparisonId"] if kind == "comparisons" else value["proposalId"]


def _comparison_identity(value: dict[str, Any]) -> tuple[str, ...]:
    identity = (
        value["baselineRunId"],
        value["treatmentRunId"],
        value["planSha256"],
    )
    if value.get("schemaVersion") == 2:
        fingerprints = value["derivedViewFingerprints"]
        return (*identity, fingerprints["baseline"], fingerprints["treatment"])
    return identity


class EvaluationStore:
    def __init__(
        self,
        state_root: Path | None = None,
        *,
        clock: types.Clock | None = None,
        ids: types.IdProvider | None = None,
        lock_timeout: float = 10.0,
    ):
        self.root = (state_root or default_state_root()).resolve()
        self.clock = clock or types.SystemClock()
        self.ids = ids or types.RandomUuidProvider()
        self.lock_timeout = lock_timeout

    @property
    def registry_path(self) -> Path:
        return self.root / "registry" / "repositories.json"

    @property
    def registry_lock_path(self) -> Path:
        return self.root / "registry" / "repositories.lock"

    @property
    def secret_path(self) -> Path:
        return self.root / "secret.key"

    def _initialize_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.root, 0o700)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        # Establish the shared parent before any UUID path is resolved. On
        # Windows a concurrently-created parent can change realpath's missing
        # path error from 3 to 2 and leave only one result with a \\?\ prefix.
        (self.root / "repositories").mkdir(parents=True, exist_ok=True)

    def _load_or_create_secret(self) -> bytes:
        self._initialize_root()
        lock_path = self.root / "secret.lock"
        with FileLock(lock_path, timeout=self.lock_timeout):
            if self.secret_path.exists():
                return self._read_secret_after_creation()
            data = secrets.token_bytes(32)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                descriptor = os.open(self.secret_path, flags, 0o600)
            except FileExistsError:
                return self._read_secret_after_creation()
            try:
                os.write(descriptor, data)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if os.name != "nt":
                os.chmod(self.secret_path, 0o600)
            harness_state.sync_directory(self.root)
            return data

    def _read_secret_after_creation(self) -> bytes:
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                data = self.secret_path.read_bytes()
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise StoreError("evaluation secret could not be read") from exc
            else:
                if len(data) == 32:
                    return data
                if len(data) > 32 or time.monotonic() >= deadline:
                    raise StoreError("evaluation secret has an invalid length")
            time.sleep(0.01)

    def _hmac(self, value: bytes) -> str:
        return hmac.digest(self._load_or_create_secret(), value, "sha256").hex()

    def pseudonym(self, repository_id: str, object_kind: str, logical_name: str) -> str:
        self._validate_repository_id(repository_id)
        if not re.fullmatch(r"[a-z][a-z0-9-]*", object_kind):
            raise StoreError("pseudonym object kind must be a lowercase identifier")
        material = b"\0".join(
            (repository_id.encode("ascii"), object_kind.encode("ascii"), logical_name.encode("utf-8"))
        )
        return f"{object_kind}:{self._hmac(material)[:32]}"

    def fingerprint(self, value: bytes) -> str:
        return self._hmac(value)

    def register_repository(self, repository: Path, *, compared_worktrees: Iterable[Path] = ()) -> str:
        ensure_state_outside_repositories(self.root, [repository, *compared_worktrees])
        locator = self._hmac(canonical_repository_root(repository).encode("utf-8"))
        with FileLock(self.registry_lock_path, timeout=self.lock_timeout):
            if self.registry_path.exists():
                try:
                    registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise StoreError(f"repository registry is invalid: {exc}") from exc
            else:
                registry = {"schemaVersion": 1, "repositories": {}}
            if not isinstance(registry, dict) or registry.get("schemaVersion") != 1 or not isinstance(registry.get("repositories"), dict):
                raise StoreError("repository registry must be a schemaVersion 1 object")
            repositories = registry["repositories"]
            repository_id = repositories.get(locator)
            if repository_id is None:
                repository_id = str(self.ids.new_uuid())
                repositories[locator] = repository_id
                _atomic_json(self.registry_path, registry)
            self._validate_repository_id(repository_id)
        self._ensure_repository_dirs(repository_id)
        return repository_id

    def _validate_repository_id(self, repository_id: str) -> None:
        if not isinstance(repository_id, str) or not REPOSITORY_ID_RE.fullmatch(repository_id):
            raise StoreError("repository id must be a canonical UUID")

    def repository_root(self, repository_id: str) -> Path:
        self._validate_repository_id(repository_id)
        try:
            return harness_state.resolve_inside(self.root, f"repositories/{repository_id}")
        except harness_state.StateError as exc:
            raise StoreError(f"repository state path escaped the reserved state root: {exc}") from exc

    def _ensure_repository_dirs(self, repository_id: str) -> Path:
        root = self.repository_root(repository_id)
        for relative in (
            "runs/pending",
            "runs/completed",
            "annotations",
            "observations",
            "comparisons",
            "proposals",
            "quarantine",
            "locks",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        return root

    def repository_lock(self, repository_id: str) -> FileLock:
        root = self._ensure_repository_dirs(repository_id)
        return FileLock(root / "locks" / "repository.lock", timeout=self.lock_timeout)

    def _run_paths(self, repository_id: str, run_id: str) -> tuple[Path, Path]:
        self._validate_repository_id(repository_id)
        try:
            canonical_run_id = str(types.uuid.UUID(run_id))
        except (ValueError, AttributeError) as exc:
            raise StoreError("run id must be a UUID") from exc
        if canonical_run_id != run_id.lower():
            raise StoreError("run id must use canonical UUID form")
        root = self._ensure_repository_dirs(repository_id) / "runs"
        return root / "pending" / f"{run_id}.json", root / "completed" / f"{run_id}.json"

    def create_pending(self, record: dict[str, Any]) -> None:
        sealed = types.seal_record(record)
        types.validate_run_record(sealed)
        if sealed["recordState"] != "pending":
            raise StoreError("create_pending requires a pending record")
        repository_id = sealed["repository"]["repositoryId"]
        pending, completed = self._run_paths(repository_id, sealed["runId"])
        with self.repository_lock(repository_id):
            if pending.exists() or completed.exists():
                raise StoreError(f"run id already exists: {sealed['runId']}")
            _atomic_json(pending, sealed)

    def update_pending(self, record: dict[str, Any]) -> None:
        sealed = types.seal_record(record)
        types.validate_run_record(sealed)
        if sealed["recordState"] != "pending":
            raise StoreError("update_pending requires a pending record")
        repository_id = sealed["repository"]["repositoryId"]
        pending, completed = self._run_paths(repository_id, sealed["runId"])
        with self.repository_lock(repository_id):
            if not pending.is_file() or completed.exists():
                raise StoreError("pending run does not exist or is already completed")
            _atomic_json(pending, sealed)

    def complete_run(self, record: dict[str, Any]) -> None:
        sealed = types.seal_record(record)
        types.validate_run_record(sealed)
        if sealed["recordState"] != "completed":
            raise StoreError("complete_run requires a completed record")
        repository_id = sealed["repository"]["repositoryId"]
        pending, completed = self._run_paths(repository_id, sealed["runId"])
        with self.repository_lock(repository_id):
            if completed.exists():
                raise StoreError("completed records are immutable")
            if not pending.is_file():
                raise StoreError("pending run does not exist")
            _atomic_json(completed, sealed)
            pending.unlink()
            harness_state.sync_directory(pending.parent)

    def read_run(self, repository_id: str, run_id: str, *, allow_pending: bool = True) -> dict[str, Any]:
        pending, completed = self._run_paths(repository_id, run_id)
        path = completed if completed.is_file() else pending if allow_pending and pending.is_file() else None
        if path is None:
            raise StoreError(f"run does not exist: {run_id}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StoreError(f"run record is unreadable: {exc}") from exc
        types.validate_run_record(record)
        return record

    def find_run(self, run_id: str) -> tuple[str, dict[str, Any]]:
        repositories_root = self.root / "repositories"
        if not repositories_root.is_dir():
            raise StoreError(f"run does not exist: {run_id}")
        matches: list[tuple[str, Path]] = []
        for repository in repositories_root.iterdir():
            if not repository.is_dir() or not REPOSITORY_ID_RE.fullmatch(repository.name):
                continue
            for state in ("completed", "pending"):
                candidate = repository / "runs" / state / f"{run_id}.json"
                if candidate.is_file():
                    matches.append((repository.name, candidate))
        if len(matches) != 1:
            raise StoreError(f"run id resolved to {len(matches)} records: {run_id}")
        repository_id, _ = matches[0]
        return repository_id, self.read_run(repository_id, run_id)

    def add_annotation(self, repository_id: str, annotation: dict[str, Any]) -> Path:
        sealed = types.seal_record(annotation)
        types.validate_annotation(sealed)
        if sealed.get("repositoryId") not in {None, repository_id}:
            raise StoreError("annotation repository id does not match the storage scope")
        self.read_run(repository_id, sealed["runId"], allow_pending=False)
        directory = self._ensure_repository_dirs(repository_id) / "annotations" / sealed["runId"]
        path = directory / f"{sealed['annotationId']}.json"
        with self.repository_lock(repository_id):
            if path.exists():
                raise StoreError("annotation id already exists")
            existing = self._read_json_records(directory, types.validate_annotation)
            if sealed["schemaVersion"] == 2:
                state = evaluation_view.annotation_state(
                    existing, repository_id=repository_id, run_id=sealed["runId"]
                )
                if state["conflicts"]:
                    raise StoreError("annotation-conflict prevents a new active annotation")
                active = state["active"]
                target = sealed["supersedesAnnotationId"]
                if target is None and active is not None:
                    raise StoreError("a new annotation must supersede the active annotation")
                if target is not None and (active is None or active["annotationId"] != target):
                    raise StoreError("annotation replacement target is not active")
            _atomic_json(path, sealed)
        return path

    def _read_json_records(self, directory: Path, validator, *, skip_invalid: bool = False) -> list[dict[str, Any]]:
        if not directory.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                validator(value)
            except (OSError, UnicodeError, json.JSONDecodeError, types.EvaluationError) as exc:
                if skip_invalid:  # Repair has already reported these files explicitly.
                    continue
                raise StoreError(f"evaluation record is invalid: {path.relative_to(directory).as_posix()}; run repair before interpreting or changing this history") from exc
            records.append(value)
        return records

    def add_observation(self, repository_id: str, observation: dict[str, Any]) -> Path:
        sealed = types.seal_record(observation)
        types.validate_observation_record(sealed)
        if sealed["repositoryId"] != repository_id:
            raise StoreError("observation repository id does not match the storage scope")
        self.read_run(repository_id, sealed["runId"], allow_pending=False)
        directory = self._ensure_repository_dirs(repository_id) / "observations"
        path = directory / f"{sealed['observationId']}.json"
        with self.repository_lock(repository_id):
            if path.exists():
                raise StoreError("observation id already exists")
            existing = [
                item for item in self._read_json_records(directory, types.validate_observation_record)
                if item.get("runId") == sealed["runId"]
            ]
            state = evaluation_view.observation_graph(
                existing, repository_id=repository_id, run_id=sealed["runId"]
            )
            if state["conflicts"]:
                raise StoreError("observation graph conflict prevents lifecycle mutation")
            kind = sealed["lifecycle"]["kind"]
            target = sealed["lifecycle"]["supersedesObservationId"]
            if kind in {"replacement", "withdrawal"}:
                active_ids = {item["observationId"] for item in state["active"]}
                if target not in active_ids:
                    raise StoreError("observation supersession target is not active")
            _atomic_json(path, sealed)
        return path

    def observations_for_run(self, repository_id: str, run_id: str) -> list[dict[str, Any]]:
        self.read_run(repository_id, run_id, allow_pending=False)
        directory = self._ensure_repository_dirs(repository_id) / "observations"
        with self.repository_lock(repository_id):
            values = [item for item in self._read_json_records(directory, types.validate_observation_record) if item.get("runId") == run_id]
        return values

    def find_observation(self, observation_id: str) -> tuple[str, dict[str, Any]]:
        try:
            if str(types.uuid.UUID(observation_id)) != observation_id.lower():
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise StoreError("observation id must be a canonical UUID") from exc
        repositories_root = self.root / "repositories"
        matches: list[tuple[str, Path]] = []
        if repositories_root.is_dir():
            for repository in repositories_root.iterdir():
                candidate = repository / "observations" / f"{observation_id}.json"
                if candidate.is_file() and REPOSITORY_ID_RE.fullmatch(repository.name):
                    matches.append((repository.name, candidate))
        if len(matches) != 1:
            raise StoreError(f"observation id resolved to {len(matches)} records: {observation_id}")
        repository_id, path = matches[0]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StoreError(f"observation record is unreadable: {exc}") from exc
        types.validate_observation_record(value)
        return repository_id, value

    def annotations_for_run(self, repository_id: str, run_id: str) -> list[dict[str, Any]]:
        self.read_run(repository_id, run_id, allow_pending=False)
        directory = self._ensure_repository_dirs(repository_id) / "annotations" / run_id
        with self.repository_lock(repository_id):
            values = self._read_json_records(directory, types.validate_annotation)
        return values

    def write_auxiliary(self, repository_id: str, kind: str, record_id: str, value: dict[str, Any]) -> Path:
        if kind not in {"comparisons", "proposals"}:
            raise StoreError("auxiliary record kind is invalid")
        try:
            if str(types.uuid.UUID(record_id)) != record_id.lower():
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise StoreError("auxiliary record id must be a canonical UUID") from exc
        sealed = types.seal_record(value)
        if kind == "comparisons":
            types.validate_comparison_record(sealed)
        else:
            types.validate_proposal_record(sealed)
        if record_id != _auxiliary_record_id(kind, sealed):
            raise StoreError("auxiliary filename id does not match the record id")
        if repository_id != sealed["repositoryId"]:
            raise StoreError("auxiliary repository id does not match the storage scope")
        path = self._ensure_repository_dirs(repository_id) / kind / f"{record_id}.json"
        with self.repository_lock(repository_id):
            if path.exists():
                raise StoreError(f"{kind[:-1]} id already exists")
            if kind == "comparisons":
                identity = _comparison_identity(sealed)
                for existing in self._read_json_records(path.parent, types.validate_comparison_record):
                    existing_identity = _comparison_identity(existing)
                    if existing_identity == identity:
                        raise StoreError(
                            "comparison already exists for this run pair and plan with the same derived views"
                        )
            _atomic_json(path, sealed)
        return path

    def list_runs(self, repository_id: str | None = None) -> list[dict[str, Any]]:
        repositories_root = self.root / "repositories"
        if not repositories_root.is_dir():
            return []
        roots = [self.repository_root(repository_id)] if repository_id else [
            item for item in repositories_root.iterdir() if item.is_dir() and REPOSITORY_ID_RE.fullmatch(item.name)
        ]
        result: list[dict[str, Any]] = []
        for root in roots:
            for state in ("pending", "completed"):
                directory = root / "runs" / state
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.json")):
                    try:
                        record = json.loads(path.read_text(encoding="utf-8"))
                        types.validate_run_record(record)
                        result.append(
                            {
                                "repositoryId": root.name,
                                "runId": record["runId"],
                                "recordState": record["recordState"],
                                "startedAt": record["timestamps"]["startedAt"],
                                "completion": record["outcome"]["completion"],
                                "schemaVersion": record["schemaVersion"],
                                "legacyReadOnly": record["schemaVersion"] == 1,
                            }
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError, types.EvaluationError):
                        result.append({"repositoryId": root.name, "path": path.name, "recordState": "corrupt"})
        return sorted(result, key=lambda item: (item.get("startedAt", ""), item.get("runId", item.get("path", ""))))

    def export_repository(self, repository_id: str) -> dict[str, Any]:
        root = self._ensure_repository_dirs(repository_id)
        included: list[dict[str, Any]] = []
        excluded = 0
        with self.repository_lock(repository_id):
            snapshot = sorted(
                path
                for directory in ("runs/completed", "annotations", "observations", "comparisons", "proposals")
                for path in (root / directory).rglob("*.json")
            )
            for path in snapshot:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    types.verify_integrity(value)
                except (OSError, UnicodeError, json.JSONDecodeError, types.EvaluationError):
                    excluded += 1
                    continue
                included.append(self._redact_export(value))
        return {
            "schemaVersion": 1,
            "repositoryId": repository_id,
            "records": included,
            "includedCount": len(included),
            "excludedCount": excluded,
            "localMappingsIncluded": False,
            "localSecretIncluded": False,
        }

    def _redact_export(self, value: Any, key: str | None = None) -> Any:
        local_only = {
            "promptFingerprint",
            "modelRef",
            "resultFingerprint",
            "repositoryLocator",
        }
        if key in local_only:
            return None
        if isinstance(value, dict):
            return {item_key: self._redact_export(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_export(item) for item in value]
        return value

    def purge_repository(self, repository_id: str) -> dict[str, Any]:
        root = self._ensure_repository_dirs(repository_id)
        removed = 0
        preserved = 0
        mapping_removed = False
        with self.repository_lock(repository_id):
            pending = list((root / "runs" / "pending").glob("*.json"))
            preserved = len(pending)
            for relative in ("runs/completed", "annotations", "observations", "comparisons", "proposals", "quarantine"):
                directory = root / relative
                if not directory.exists():
                    continue
                for path in sorted(directory.rglob("*.json"), reverse=True):
                    path.unlink()
                    removed += 1
                for directory_path in sorted((item for item in directory.rglob("*") if item.is_dir()), reverse=True):
                    try:
                        directory_path.rmdir()
                    except OSError:
                        pass
        if preserved == 0:
            with FileLock(self.registry_lock_path, timeout=self.lock_timeout):
                if self.registry_path.is_file():
                    try:
                        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                        raise StoreError(f"repository registry is invalid: {exc}") from exc
                    repositories = registry.get("repositories") if isinstance(registry, dict) else None
                    if not isinstance(repositories, dict):
                        raise StoreError("repository registry must be a schemaVersion 1 object")
                    locators = [locator for locator, value in repositories.items() if value == repository_id]
                    for locator in locators:
                        del repositories[locator]
                    if locators:
                        _atomic_json(self.registry_path, registry)
                        mapping_removed = True
        return {
            "repositoryId": repository_id,
            "removed": removed,
            "activePendingPreserved": preserved,
            "registryMappingRemoved": mapping_removed,
        }

    def repair_repository(self, repository_id: str, *, quarantine: bool = False) -> dict[str, Any]:
        root = self._ensure_repository_dirs(repository_id)
        invalid: list[dict[str, str]] = []
        moved = 0
        with self.repository_lock(repository_id):
            candidates = sorted(
                path
                for relative in ("runs/pending", "runs/completed", "annotations", "observations", "comparisons", "proposals")
                for path in (root / relative).rglob("*.json")
            )
            for path in candidates:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    types.verify_integrity(value)
                    relative = path.relative_to(root)
                    record_kind = relative.parts[0] if relative.parts else ""
                    if "recordState" in value:
                        types.validate_run_record(value)
                    elif "annotationId" in value:
                        types.validate_annotation(value)
                    elif "observationId" in value:
                        types.validate_observation_record(value)
                    elif "comparisonId" in value:
                        types.validate_comparison_record(value)
                        if record_kind != "comparisons":
                            raise types.EvaluationError("comparison record is stored under the wrong kind")
                        if path.stem != value["comparisonId"]:
                            raise types.EvaluationError("comparison filename id does not match the record id")
                        if value["repositoryId"] != repository_id:
                            raise types.EvaluationError("comparison repository id does not match the storage scope")
                    elif "proposalId" in value:
                        types.validate_proposal_record(value)
                        if record_kind != "proposals":
                            raise types.EvaluationError("proposal record is stored under the wrong kind")
                        if path.stem != value["proposalId"]:
                            raise types.EvaluationError("proposal filename id does not match the record id")
                        if value["repositoryId"] != repository_id:
                            raise types.EvaluationError("proposal repository id does not match the storage scope")
                    else:
                        raise types.EvaluationError("unknown evaluation record type")
                except (OSError, UnicodeError, json.JSONDecodeError, types.EvaluationError) as exc:
                    digest = harness_state.digest_bytes(path.read_bytes()) if path.is_file() else "missing"
                    invalid.append({"path": str(path.relative_to(root)).replace("\\", "/"), "digest": digest, "error": type(exc).__name__})
                    if quarantine and path.is_file():
                        target = root / "quarantine" / f"{path.stem}-{digest[:12]}.json"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(path, target)
                        moved += 1
            observation_records = self._read_json_records(root / "observations", types.validate_observation_record, skip_invalid=True)
            observation_runs = {
                item.get("runId") for item in observation_records if isinstance(item.get("runId"), str)
            }
            for run_id in sorted(observation_runs):
                graph = evaluation_view.observation_graph(
                    [item for item in observation_records if item.get("runId") == run_id],
                    repository_id=repository_id,
                    run_id=run_id,
                )
                for conflict in graph["conflicts"]:
                    invalid.append({
                        "path": f"observations/{run_id}",
                        "digest": "graph",
                        "error": conflict["code"],
                    })
            annotation_root = root / "annotations"
            annotation_runs = [item for item in annotation_root.iterdir() if item.is_dir()] if annotation_root.is_dir() else []
            for run_directory in annotation_runs:
                state = evaluation_view.annotation_state(
                    self._read_json_records(run_directory, types.validate_annotation, skip_invalid=True),
                    repository_id=repository_id,
                    run_id=run_directory.name,
                )
                for conflict in state["conflicts"]:
                    invalid.append({
                        "path": f"annotations/{run_directory.name}",
                        "digest": "graph",
                        "error": conflict["code"],
                    })
            if quarantine and invalid:
                index = {
                    "schemaVersion": 1,
                    "discoveredAt": types.timestamp_text(self.clock.now_utc()),
                    "items": invalid,
                }
                _atomic_json(root / "quarantine" / "index.json", index)
        return {"repositoryId": repository_id, "invalid": invalid, "quarantined": moved}
