#!/usr/bin/env python3
"""Single source of current Harness release and schema metadata."""

from __future__ import annotations


RUNTIME = "codex"
HARNESS_VERSION = "6.8"

PLAN_SCHEMA_VERSION = 3
MANIFEST_SCHEMA_VERSION = 5
TRANSACTION_SCHEMA_VERSION = 2
EVALUATION_SCHEMA_VERSION = 2

READABLE_EVALUATION_VERSIONS = frozenset(
    {"6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", HARNESS_VERSION}
)
ATTRIBUTION_ELIGIBLE_EVALUATION_VERSIONS = frozenset({HARNESS_VERSION})
