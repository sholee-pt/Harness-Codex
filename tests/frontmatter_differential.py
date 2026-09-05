"""Optional independent YAML comparison. Run with the Conda harness Python."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents/skills/harness/scripts"))
import harness_frontmatter


def candidates(seed: int, count: int):
    rng = random.Random(seed)
    alphabet = "abXY019 -_:#{}[],.'\"\\/!?&*|>+~\t\r\n\u00a0\u0085\u2028α한😀"
    for index in range(count):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 55)))
        mode = index % 4
        raw = (value, json.dumps(value, ensure_ascii=False), "'" + value.replace("'", "''") + "'", '"' + value + '"')[mode]
        yield "---\nname: project-harness\ndescription: " + raw + "\n---\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--count", type=int, default=11000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        import yaml
    except ImportError:
        parser.error("Install the optional tests/requirements-validation.txt into a test-only environment or target directory; runtime has no YAML dependency.")
    corpus_path = ROOT / "tests/fixtures/frontmatter-cases.json"
    corpus = json.loads(corpus_path.read_text())["cases"]
    failures = []
    accepted = rejected = 0
    input_hash = hashlib.sha256()
    # Fixed expected values test both supported acceptance and deliberate refusal.
    for case in corpus:
        try:
            result = harness_frontmatter.parse(case["header"])
        except harness_frontmatter.FrontmatterError:
            result = None
        if result != case["expected"]:
            failures.append({"case": case["id"], "expected": case["expected"], "actual": result})
    # Differential testing concerns accepted strings only: YAML accepts many
    # constructs deliberately outside the generated-skills subset.
    for index, header in enumerate(candidates(args.seed, args.count)):
        input_hash.update(json.dumps(header, ensure_ascii=True).encode("ascii") + b"\n")
        try:
            actual = harness_frontmatter.parse(header)
        except harness_frontmatter.FrontmatterError:
            rejected += 1
            continue
        accepted += 1
        try:
            expected = yaml.safe_load(header.replace("\r\n", "\n").split("---\n", 2)[1])
        except yaml.YAMLError as exc:
            expected = {"yamlError": str(exc)}
        if expected != actual:
            failures.append({"index": index, "header": header, "expected": expected, "actual": actual})
    surrogate = r'"\ud83d\ude00"'
    yaml_surrogate = yaml.safe_load("description: " + surrogate)["description"]
    report = {
        "schemaVersion": 1, "seed": args.seed, "candidateCount": args.count,
        "fixedCaseCount": len(corpus), "accepted": accepted, "rejected": rejected,
        "pyYamlVersion": yaml.__version__, "pythonVersion": sys.version.split()[0],
        "generatorSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "corpusSha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "generatedInputsSha256": input_hash.hexdigest(),
        "surrogateReferenceCodePoints": [f"U+{ord(c):04X}" for c in yaml_surrogate],
        "surrogatePolicy": "reject escaped surrogate code units; allow literal Unicode scalar values",
        "failures": failures, "valid": not failures,
        "provesCompleteYamlSupport": False, "liveCodexInvoked": False,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
