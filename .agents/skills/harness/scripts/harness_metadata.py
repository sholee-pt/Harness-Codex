#!/usr/bin/env python3
"""Single source of current Harness release and schema metadata."""

from __future__ import annotations


RUNTIME = "codex"
HARNESS_VERSION = "0.11.0-beta"
AUTHORING_CONTRACT_VERSION = 3
ARTIFACT_CONTRACT_VERSION = 2
# Installation compatibility follows the artifact contract, not release equality.
# Only explicitly supported releases may enter the normal update path.
ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS = frozenset({"9.0", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10", "9.11", "0.10.0-beta", HARNESS_VERSION})
ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS |= frozenset(f"0.9.{patch}-beta" for patch in range(12))
PREVIOUS_ARTIFACT_GENERATOR_VERSIONS = frozenset({"8.0", "8.1"})
INVENTORY_SCHEMA_VERSION = 5
ROOT_CONTEXT_SCHEMA_VERSION = 3

PLAN_SCHEMA_VERSION = 3
MANIFEST_SCHEMA_VERSION = 7
PREVIOUS_MANIFEST_SCHEMA_VERSION = 6
TRANSACTION_SCHEMA_VERSION = 2
EVALUATION_SCHEMA_VERSION = 2
OPERATIONS_EVENT_SCHEMA_VERSION = 1

READABLE_EVALUATION_VERSIONS = frozenset(
    {
        "6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9",
        "6.10", "7.0", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "8.0", "8.1", "9.0", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.7", "9.8", "9.9", "9.10", "9.11", "0.10.0-beta", HARNESS_VERSION,
    }
)
ATTRIBUTION_ELIGIBLE_EVALUATION_VERSIONS = frozenset({HARNESS_VERSION})


def artifact_contract_state(manifest: dict) -> str:
    """Classify version provenance, never the integrity of installed files."""
    generator = manifest.get("generator")
    if not isinstance(generator, dict):
        raise ValueError("manifest generator must be an object")
    version = generator.get("version")
    if not isinstance(version, str):
        raise ValueError("generator.version must be a string")
    schema = manifest.get("schemaVersion")
    contract = manifest.get("artifactContractVersion")
    scope = manifest.get("workspace", {}).get("scope") if isinstance(manifest.get("workspace"), dict) else None
    if type(schema) is int and schema == PREVIOUS_MANIFEST_SCHEMA_VERSION and scope == "local-only":
        if version in {f"7.{minor}" for minor in range(7)} and "artifactContractVersion" not in manifest:
            return "legacy"
        if version in PREVIOUS_ARTIFACT_GENERATOR_VERSIONS and type(contract) is int and contract == 1:
            return "workspace-upgrade"
        raise ValueError("unsupported generator/artifact contract combination for legacy workspace")
    if version not in ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS:
        raise ValueError("unsupported generator/artifact contract combination")
    if (type(schema) is not int or schema != MANIFEST_SCHEMA_VERSION or scope != "project-local"
            or type(contract) is not int or contract != ARTIFACT_CONTRACT_VERSION):
        raise ValueError("current generator requires schemaVersion 7, project-local scope and artifactContractVersion 2; inconsistent metadata may indicate an incomplete upgrade")
    return "current"
