"""Render and validate the topology-bound portion of an agent's instructions."""

from __future__ import annotations

import copy
import json
import re
import tomllib


PLACEHOLDER = "{{HARNESS_AGENT_CONTRACT_V1}}"
BEGIN = "<!-- harness:agent-contract:v1:begin -->"
END = "<!-- harness:agent-contract:v1:end -->"


class AgentContractError(ValueError):
    pass


def render(agent: dict, topology: dict) -> str:
    names = {access["phase"] for access in agent["fileAccess"]}
    contract = {
        "name": agent["name"],
        "responsibility": agent["responsibility"],
        "scope": agent["scope"],
        "boundaryRefs": agent.get("boundaryRefs", []),
        "skills": agent.get("skills", []),
        "fileAccess": agent["fileAccess"],
        "executionPhases": [phase for phase in topology["executionPhases"] if phase["id"] in names],
        "handoffs": [handoff for handoff in topology["handoffs"] if agent["name"] in (handoff["fromAgent"], handoff["toAgent"])],
    }
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (
        BEGIN + "\n## Assigned contract\n\n"
        "Use this topology-derived contract for responsibility, access lanes, dependencies and handoffs. "
        "A task may narrow these scopes; other prose cannot expand them. "
        "Report conflicting instructions to the parent before affected work. "
        "These are task constraints, not an operating-system sandbox.\n\n```json\n"
        + payload + "\n```\n" + END
    )


def validate(instructions: str, agent: dict, topology: dict, *, allow_missing: bool = False) -> None:
    if PLACEHOLDER in instructions:
        raise AgentContractError(f"agent {agent['name']} has an unmaterialized contract placeholder")
    if allow_missing and BEGIN not in instructions and END not in instructions:
        return
    expected = render(agent, topology)
    normalized = instructions.replace("\r\n", "\n")
    if normalized.count(BEGIN) != 1 or normalized.count(END) != 1 or normalized.count(expected) != 1:
        raise AgentContractError(f"agent {agent['name']} contract is missing, duplicated, or differs from topology")


def _string_end(content: str, start: int) -> int:
    quote = content[start:start + 1]
    if quote not in {'"', "'"}:
        raise AgentContractError("developer_instructions must be a TOML string")
    triple = content[start:start + 3] == quote * 3
    index = start + (3 if triple else 1)
    while index < len(content):
        if quote == '"' and content[index] == "\\":
            index += 2
            continue
        if content[index] == quote:
            if not triple:
                return index + 1
            end = index
            while end < len(content) and content[end] == quote:
                end += 1
            if end - index >= 3:
                return end
            index = end
        else:
            index += 1
    raise AgentContractError("unclosed developer_instructions string")


def replace_instructions(content: str, instructions: str) -> str:
    """Replace a string without rewriting any other TOML configuration value.

    Candidate matches inside another multiline value are rejected by reparsing
    and comparing the entire TOML object, rather than trusting a line regex.
    """
    original = tomllib.loads(content)
    expected = copy.deepcopy(original)
    expected["developer_instructions"] = instructions
    replacement = json.dumps(instructions, ensure_ascii=False)
    candidates = []
    for match in re.finditer(r"(?m)^[ \t]*(?:developer_instructions|\"developer_instructions\"|'developer_instructions')[ \t]*=[ \t]*", content):
        try:
            end = _string_end(content, match.end())
            candidate = content[:match.end()] + replacement + content[end:]
            if tomllib.loads(candidate) == expected:
                candidates.append(candidate)
        except (ValueError, IndexError):
            continue
    if len(candidates) != 1:
        raise AgentContractError("cannot unambiguously replace developer_instructions while preserving TOML settings")
    return candidates[0]


def materialize(content: str, agent: dict, topology: dict) -> str:
    data = tomllib.loads(content)
    instructions = data.get("developer_instructions")
    if not isinstance(instructions, str):
        raise AgentContractError("developer_instructions must be a string")
    if instructions.count(PLACEHOLDER) == 1 and BEGIN not in instructions and END not in instructions:
        updated = instructions.replace(PLACEHOLDER, render(agent, topology))
        validate(updated, agent, topology)
        return replace_instructions(content, updated)
    validate(instructions, agent, topology)
    return content
