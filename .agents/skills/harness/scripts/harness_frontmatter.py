"""String-only, single-line YAML subset for generated skills (stdlib only)."""

from __future__ import annotations

import json
import re
import unicodedata


class FrontmatterError(ValueError):
    pass


def _text(value: str) -> str:
    if not value.strip():
        raise FrontmatterError("frontmatter values must be non-empty strings")
    if any(unicodedata.category(c) in {"Cc", "Cs"} or c in "\u2028\u2029\ufffe\uffff" for c in value):
        raise FrontmatterError("control characters, surrogates and line separators are unsupported")
    return value


def _tail(value: str) -> None:
    if value and not re.fullmatch(r" +(?:#.*)?", value):
        raise FrontmatterError("quoted values require ASCII spacing before an optional comment")


def parse_scalar(raw: str) -> str:
    """Decode only the documented subset; never coerce YAML non-string values."""
    if not raw:
        raise FrontmatterError("missing frontmatter value")
    if raw.startswith('"'):
        # Reject escaped surrogate code units before JSON can combine a pair.
        # A literal emoji is allowed; a literal backslash-u sequence is distinct.
        index = 1
        while index < len(raw):
            if raw[index] == '"':
                break
            if raw[index] == "\\":
                if raw[index + 1:index + 2] == "u":
                    digits = raw[index + 2:index + 6]
                    if re.fullmatch(r"[0-9a-fA-F]{4}", digits) and 0xD800 <= int(digits, 16) <= 0xDFFF:
                        raise FrontmatterError("surrogate escapes are unsupported; use literal Unicode")
                index += 2
            else:
                index += 1
        try:
            value, end = json.JSONDecoder().raw_decode(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise FrontmatterError("invalid JSON-compatible quoted string") from exc
        _tail(raw[end:])
        return _text(value)
    if raw.startswith("'"):
        result: list[str] = []
        index = 1
        while index < len(raw):
            if raw[index] == "'":
                if raw[index + 1:index + 2] == "'":
                    result.append("'")
                    index += 2
                    continue
                _tail(raw[index + 1:])
                return _text("".join(result))
            result.append(raw[index])
            index += 1
        raise FrontmatterError("unclosed single-quoted string")
    value = re.split(r" +#", raw, maxsplit=1)[0].rstrip(" ")
    if not value or value[0] in "-?:,[]{}#&*!|>'\"%@`" or ": " in value or value.endswith(":"):
        raise FrontmatterError("unsupported plain scalar syntax; quote the string")
    if value.lower() in {"~", "null", "true", "false", "yes", "no", "on", "off", ".inf", "+.inf", "-.inf", ".nan"}:
        raise FrontmatterError("ambiguous non-string scalar; quote the string")
    # Conservative rule also excludes dates, sexagesimal numbers and numeric
    # formats on which YAML 1.1/1.2 loaders disagree. Quote these descriptions.
    if re.match(r"[+\-.0-9]", value):
        raise FrontmatterError("numeric-looking scalar; quote the string")
    return _text(value)


def parse(text: str) -> dict[str, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise FrontmatterError("missing exact opening YAML frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise FrontmatterError("missing exact closing YAML frontmatter delimiter") from exc
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if any(unicodedata.category(c) in {"Cc", "Cs"} or c in "\u2028\u2029\ufffe\uffff" for c in line):
            raise FrontmatterError("unsupported frontmatter character or spacing")
        if not line.strip(" ") or line.lstrip(" ").startswith("#"):
            continue
        match = re.fullmatch(r"(name|description): +(.*)", line)
        if match is None:
            raise FrontmatterError("only unindented name and description keys with ASCII spacing are supported")
        key, raw = match.groups()
        if key in result:
            raise FrontmatterError(f"duplicate frontmatter key: {key}")
        result[key] = parse_scalar(raw)
    if set(result) != {"name", "description"}:
        raise FrontmatterError("frontmatter requires exactly name and description")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result["name"]) or len(result["name"]) > 64:
        raise FrontmatterError("name must be a kebab-case string of at most 64 characters")
    if len(result["description"]) > 1024:
        raise FrontmatterError("description must be at most 1024 characters")
    return result


def render(name: str, description: str) -> str:
    """Produce one canonical, literal-Unicode header for supported values."""
    header = "---\nname: " + json.dumps(name, ensure_ascii=False) + "\ndescription: " + json.dumps(description, ensure_ascii=False) + "\n---\n"
    parse(header)
    return header
