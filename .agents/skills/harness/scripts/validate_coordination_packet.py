#!/usr/bin/env python3
"""Validate one parent-facing Harness coordination packet without writing state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import harness_coordination
import validate_runtime_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--packet", required=True)
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        validate_runtime_plan.validate_runtime_plan(root, plan)
        report = harness_coordination.validate_coordination_packet(
            packet,
            participants=harness_coordination.participant_map(plan),
            tasks=harness_coordination.task_map(plan),
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        harness_coordination.CoordinationPacketError,
        validate_runtime_plan.RuntimePlanError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": harness_coordination.PACKET_SCHEMA_VERSION,
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
