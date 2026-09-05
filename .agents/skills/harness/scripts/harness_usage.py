#!/usr/bin/env python3
"""Presentation-only usage coverage; never sum overlapping or unverified scopes."""

from __future__ import annotations

import copy
from typing import Any

import harness_eval_types as types


TOKEN_METRICS = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens")


def usage_summary(run: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """Keep reported, unavailable and conflicted values distinct from selected usage.

    This supplement is attached only to CLI output. It is not persisted, included
    in comparison view fingerprints, or used to promote metric completeness.
    """
    types.validate_run_record(run)
    if view.get("runId") != run["runId"] or view.get("repositoryId") != run["repository"]["repositoryId"]:
        raise types.EvaluationError("usage view does not belong to the run")
    selected = view["selectedValues"]
    conflicts = {item.get("field") for item in view["activeConflicts"]}
    metrics = {}
    for name in TOKEN_METRICS:
        field = f"measurements.{name}"
        chosen = selected.get(field)
        if field in conflicts:
            selection = "conflicted"
            measurement = None
        elif isinstance(chosen, dict):
            selection = "selected"
            measurement = copy.deepcopy(chosen)
        else:
            measurement = copy.deepcopy(run["measurements"][name])
            selection = "reported-only" if measurement["state"] == "measured" else "unavailable"
        metrics[name] = {
            "selection": selection,
            "measurement": measurement,
            "scope": (
                "codex-terminal-event"
                if measurement is not None and measurement["state"] == "measured"
                and measurement["source"] == "codex-jsonl"
                else "unverified"
            ),
        }
    return {
        "reportVersion": 1,
        "metrics": metrics,
        "captureMode": run["capture"]["captureMode"],
        "childUsageCoverage": "unverified",
        "accountUsageCoverage": "not-measured",
        "componentOverlap": "unverified",
        "aggregationPerformed": False,
        "totalTokens": types.unavailable("tokens"),
        "billingCost": {"state": "unavailable", "value": None},
        "limitations": [
            "Terminal usage is not proof of parent-only, all-child, or account-wide coverage.",
            "Do not add cached input or reasoning output to other counters without verified overlap semantics.",
            "Generation, operations, evaluation and unrelated runs are not included as a measured lifecycle total.",
        ],
        "persisted": False,
    }
