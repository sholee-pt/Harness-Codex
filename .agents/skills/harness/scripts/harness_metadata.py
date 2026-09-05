#!/usr/bin/env python3
"""Single source of current Harness release and schema metadata."""

from __future__ import annotations


RUNTIME = "codex"
HARNESS_VERSION = "7.6"
AUTHORING_CONTRACT_VERSION = 2
INVENTORY_SCHEMA_VERSION = 4
ROOT_CONTEXT_SCHEMA_VERSION = 2

PLAN_SCHEMA_VERSION = 3
MANIFEST_SCHEMA_VERSION = 6
TRANSACTION_SCHEMA_VERSION = 2
EVALUATION_SCHEMA_VERSION = 2
OPERATIONS_EVENT_SCHEMA_VERSION = 1

READABLE_EVALUATION_VERSIONS = frozenset(
    {
        "6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9",
        "6.10", "7.0", "7.1", "7.2", "7.3", "7.4", "7.5", HARNESS_VERSION,
    }
)
ATTRIBUTION_ELIGIBLE_EVALUATION_VERSIONS = frozenset({HARNESS_VERSION})
