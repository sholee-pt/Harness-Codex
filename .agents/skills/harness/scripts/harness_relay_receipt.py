#!/usr/bin/env python3
"""Validate packet lineage, stale reviews, and affected-agent rerun accounting."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

import harness_coordination
import validate_runtime_plan


RELAY_RECEIPT_SCHEMA_VERSION = 1
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REVIEW_STATUSES = {"accepted", "changes-requested", "blocked"}


class RelayReceiptError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def seal_relay_receipt(value: Any) -> dict[str, Any]:
    receipt = copy.deepcopy(_require_object(value, "relay receipt"))
    if "integrity" in receipt:
        raise RelayReceiptError("relay receipt is already sealed")
    receipt["integrity"] = {"algorithm": "sha256", "canonicalSha256": sha256(receipt)}
    return receipt


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RelayReceiptError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RelayReceiptError(f"{label} must be an array")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelayReceiptError(f"{label} must be non-empty text")
    return value


def _require_hash(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not HASH_RE.fullmatch(text):
        raise RelayReceiptError(f"{label} must be a SHA-256 hash")
    return text


def _require_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RelayReceiptError(f"{label} must be a non-negative integer")
    return value


def _require_text_list(value: Any, label: str) -> list[str]:
    items = _require_list(value, label)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise RelayReceiptError(f"{label} entries must be non-empty strings")
    if len(items) != len(set(items)):
        raise RelayReceiptError(f"{label} must not contain duplicates")
    return items


def _require_keys(
    value: dict[str, Any], *, required: Iterable[str], label: str
) -> None:
    expected = set(required)
    if set(value) != expected:
        missing = expected - set(value)
        extra = set(value) - expected
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unsupported " + ", ".join(sorted(extra)))
        raise RelayReceiptError(f"{label} fields are invalid: {'; '.join(details)}")


def validate_relay_receipt(
    value: Any,
    *,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Validate a separate review envelope without changing packet Schema 1."""
    receipt = _require_object(value, "relay receipt")
    _require_keys(
        receipt,
        required=(
            "schemaVersion",
            "runtimePlanSha256",
            "packetRevisions",
            "reviews",
            "reruns",
            "integration",
            "integrity",
        ),
        label="relay receipt",
    )
    if receipt.get("schemaVersion") != RELAY_RECEIPT_SCHEMA_VERSION:
        raise RelayReceiptError(
            f"relay receipt schemaVersion must be {RELAY_RECEIPT_SCHEMA_VERSION}"
        )
    expected_plan_hash = sha256(plan)
    if _require_hash(receipt.get("runtimePlanSha256"), "runtimePlanSha256") != expected_plan_hash:
        raise RelayReceiptError("relay receipt is bound to a different runtime plan")
    participants = harness_coordination.participant_map(plan)
    tasks = harness_coordination.task_map(plan)
    participant_ids = set(participants)

    revision_items = _require_list(receipt.get("packetRevisions"), "packetRevisions")
    if not revision_items:
        raise RelayReceiptError("packetRevisions must not be empty")
    revisions: dict[int, dict[str, Any]] = {}
    packet_hashes: set[str] = set()
    for index, raw in enumerate(revision_items):
        label = f"packetRevisions[{index}]"
        item = _require_object(raw, label)
        _require_keys(
            item,
            required=("revision", "packetSha256", "affectedAgents"),
            label=label,
        )
        revision = _require_integer(item.get("revision"), f"{label}.revision")
        packet_hash = _require_hash(item.get("packetSha256"), f"{label}.packetSha256")
        affected = set(_require_text_list(item.get("affectedAgents"), f"{label}.affectedAgents"))
        if affected - participant_ids:
            raise RelayReceiptError(f"{label}.affectedAgents references unknown participants")
        if revision in revisions or packet_hash in packet_hashes:
            raise RelayReceiptError("packet revisions and packet hashes must be unique")
        if revision == 0 and affected:
            raise RelayReceiptError("initial packet revision must not declare rerun agents")
        revisions[revision] = item
        packet_hashes.add(packet_hash)
    ordered = sorted(revisions)
    if ordered != list(range(len(ordered))):
        raise RelayReceiptError("packet revisions must be contiguous from zero")
    max_rounds = plan.get("communication", {}).get("maxRounds")
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool):
        raise RelayReceiptError("runtime plan communication budget is invalid")
    if len(ordered) - 1 > max_rounds:
        raise RelayReceiptError("packet revisions exceed the runtime-plan round budget")

    reviews_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_require_list(receipt.get("reviews"), "reviews")):
        label = f"reviews[{index}]"
        review = _require_object(raw, label)
        _require_keys(
            review,
            required=(
                "reviewId",
                "taskId",
                "participant",
                "revision",
                "inputPacketSha256",
                "reviewSha256",
                "status",
            ),
            label=label,
        )
        review_id = _require_text(review.get("reviewId"), f"{label}.reviewId")
        if review_id in reviews_by_id:
            raise RelayReceiptError("reviewId values must be unique")
        task_id = _require_text(review.get("taskId"), f"{label}.taskId")
        participant = _require_text(review.get("participant"), f"{label}.participant")
        revision = _require_integer(review.get("revision"), f"{label}.revision")
        if task_id not in tasks or participant not in participants:
            raise RelayReceiptError(f"{label} references an unknown task or participant")
        if tasks[task_id].get("owner") != participant:
            raise RelayReceiptError(f"{label}.participant does not own the review task")
        if participants[participant].get("runtimeRole") not in {
            "reviewer",
            "skeptic",
            "integrator",
            "supervisor",
        }:
            raise RelayReceiptError(f"{label}.participant is not a review-capable runtime role")
        if revision not in revisions:
            raise RelayReceiptError(f"{label}.revision is unknown")
        input_hash = _require_hash(review.get("inputPacketSha256"), f"{label}.inputPacketSha256")
        if input_hash != revisions[revision]["packetSha256"]:
            raise RelayReceiptError(f"{label} does not echo the reviewed packet hash")
        _require_hash(review.get("reviewSha256"), f"{label}.reviewSha256")
        if review.get("status") not in REVIEW_STATUSES:
            raise RelayReceiptError(f"{label}.status is unsupported")
        reviews_by_id[review_id] = review

    reruns: dict[int, set[str]] = {}
    for index, raw in enumerate(_require_list(receipt.get("reruns"), "reruns")):
        label = f"reruns[{index}]"
        item = _require_object(raw, label)
        _require_keys(item, required=("revision", "agents"), label=label)
        revision = _require_integer(item.get("revision"), f"{label}.revision")
        agents = set(_require_text_list(item.get("agents"), f"{label}.agents"))
        if revision == 0 or revision not in revisions or revision in reruns:
            raise RelayReceiptError(f"{label}.revision is invalid or duplicate")
        if agents - participant_ids:
            raise RelayReceiptError(f"{label}.agents references unknown participants")
        reruns[revision] = agents
    for revision in ordered[1:]:
        expected = set(revisions[revision]["affectedAgents"])
        observed = reruns.get(revision)
        if observed is None:
            raise RelayReceiptError(f"revision {revision} is missing affected-agent rerun accounting")
        if observed != expected:
            extra = observed - expected
            missing = expected - observed
            if extra:
                raise RelayReceiptError(
                    "rerun accounting includes unaffected agents: " + ", ".join(sorted(extra))
                )
            raise RelayReceiptError(
                "rerun accounting omits affected agents: " + ", ".join(sorted(missing))
            )

    integration = _require_object(receipt.get("integration"), "integration")
    _require_keys(
        integration,
        required=("packetSha256", "reviewIds", "verdict"),
        label="integration",
    )
    final_revision = revisions[ordered[-1]]
    final_hash = _require_hash(integration.get("packetSha256"), "integration.packetSha256")
    if final_hash != final_revision["packetSha256"]:
        raise RelayReceiptError("integration must use the latest packet revision")
    review_ids = _require_text_list(integration.get("reviewIds"), "integration.reviewIds")
    if not review_ids:
        raise RelayReceiptError("integration must cite at least one review")
    if set(review_ids) - set(reviews_by_id):
        raise RelayReceiptError("integration references an unknown review")
    stale_ids = [
        review_id
        for review_id in review_ids
        if reviews_by_id[review_id]["inputPacketSha256"] != final_hash
    ]
    if stale_ids:
        raise RelayReceiptError(
            "integration uses stale reviews: " + ", ".join(sorted(stale_ids))
        )
    if integration.get("verdict") not in {"accept", "reject", "blocked"}:
        raise RelayReceiptError("integration.verdict is unsupported")
    integrated_reviews = [reviews_by_id[review_id] for review_id in review_ids]
    required_review_tasks = {
        task_id
        for task_id, task in tasks.items()
        if task.get("required") is True
        and participants[task["owner"]].get("runtimeRole")
        in {"reviewer", "skeptic", "integrator", "supervisor"}
    }
    integrated_review_tasks = {review["taskId"] for review in integrated_reviews}
    missing_review_tasks = required_review_tasks - integrated_review_tasks
    if missing_review_tasks:
        raise RelayReceiptError(
            "integration omits required review tasks: "
            + ", ".join(sorted(missing_review_tasks))
        )
    if integration["verdict"] == "accept" and any(
        review["status"] != "accepted" for review in integrated_reviews
    ):
        raise RelayReceiptError("accept integration requires accepted cited reviews")
    integrity = _require_object(receipt.get("integrity"), "integrity")
    _require_keys(
        integrity,
        required=("algorithm", "canonicalSha256"),
        label="integrity",
    )
    if integrity.get("algorithm") != "sha256":
        raise RelayReceiptError("relay receipt integrity algorithm is unsupported")
    expected_integrity = _require_hash(
        integrity.get("canonicalSha256"), "integrity.canonicalSha256"
    )
    unsigned = dict(receipt)
    unsigned.pop("integrity")
    if sha256(unsigned) != expected_integrity:
        raise RelayReceiptError("relay receipt canonical hash does not match")
    return {
        "schemaVersion": RELAY_RECEIPT_SCHEMA_VERSION,
        "valid": True,
        "runtimePlanSha256": expected_plan_hash,
        "latestPacketSha256": final_hash,
        "revisionCount": len(revisions) - 1,
        "reviewCount": len(reviews_by_id),
        "rerunCount": sum(len(value) for value in reruns.values()),
        "staleReviewCount": 0,
        "receiptSha256": expected_integrity,
        "provesLiveSubagentExecution": False,
        "warnings": [],
        "errors": [],
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--seal", action="store_true", help="Seal an unsigned draft before validation")
    parser.add_argument("--output", help="Write the sealed receipt atomically")
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
        validate_runtime_plan.validate_runtime_plan(root, plan)
        if args.output and not args.seal:
            raise RelayReceiptError("--output requires --seal")
        if args.seal:
            receipt = seal_relay_receipt(receipt)
        report = validate_relay_receipt(receipt, plan=plan)
        if args.output:
            _write_json_atomic(Path(args.output).resolve(), receipt)
        print(json.dumps(receipt if args.seal else report, indent=2, ensure_ascii=False))
        return 0
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RelayReceiptError,
        validate_runtime_plan.RuntimePlanError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": RELAY_RECEIPT_SCHEMA_VERSION,
                    "valid": False,
                    "provesLiveSubagentExecution": False,
                    "warnings": [],
                    "errors": [str(exc)],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
