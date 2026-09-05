# Generated artifact contracts

Harness for Codex v8.0 requires Authoring Contract 3 drafts and Artifact Contract 1 plans and installations. Plan Schema 3 and Manifest Schema 6 describe the outer data structure; their unchanged numbers do not imply backward compatibility. The new mandatory agent block makes this a major release. Transaction Schema 2, runtime-plan Schema 1, and Evaluation Schema 2 are unchanged.

Harness for Codex v8.1 retains those contracts and checks the existing installation at the apply boundary as well as the incoming plan. The explicitly supported v8.0 and v8.1 releases share Artifact Contract 1. A v8.0 installation can remain valid under v8.1 without being relabeled by a read-only diagnostic. Unsupported future releases are not accepted by inferring compatibility from a version prefix or ordering.

## Agent instructions

Put `{{HARNESS_AGENT_CONTRACT_V1}}` exactly once inside each agent's TOML `developer_instructions`. The builder derives a marked canonical block from that agent's name, responsibility, scope, boundary references, skill dependencies, full file-access lanes, relevant execution phases, and incoming/outgoing handoffs. Describe these fields in the topology once. Use the remaining prose for project-specific methods, evidence, inputs, outputs, and verification; do not repeat scope or ownership declarations there.

The builder parses TOML before replacing the actual instruction string and verifies that every other decoded setting is preserved. A placeholder in a comment or description does not satisfy the requirement. Apply and installed-state validation compare the decoded instruction block with the topology, including read-only agents. A changed topology with an old block fails: prepare a reviewed draft with the placeholder to regenerate it. Missing, duplicate, partial, or mismatched blocks fail.

These checks establish structural agreement. They do not prove that all free prose is semantically consistent, that an agent loaded or obeyed instructions, or that file scopes are enforced by an operating-system sandbox. Report conflicting prose before affected work; tasks may narrow the contract but cannot expand it.

## Skill frontmatter subset

The runtime has no YAML dependency. Generation, apply, and installed validation use the same strict string-only subset. This is not a general YAML parser.

- Exact `---` opening and closing lines; LF or CRLF line endings.
- Exactly one unindented `name` and one unindented `description`, each followed by `:` and one or more ASCII spaces. Blank lines and ASCII-space-indented comments are permitted. Extra keys and duplicate keys fail.
- Values occupy one line. Single quotes use doubled apostrophes. Double quotes accept JSON string escapes, subject to the character restrictions below. Only ASCII spaces and an optional comment may follow a closing quote.
- Plain values preserve embedded colons without a following ASCII space, hashes without a preceding ASCII space, and literal Unicode. A space followed by `#` starts a comment. YAML indicators at the beginning, colon-space, terminal colons, null/boolean spellings, and numeric-looking prefixes require quoting. Quote collections and date-like or number-like text if a string is intended.
- Collections, block scalars, anchors, aliases, tags, YAML-only escapes, tabs, bare carriage returns, control characters, surrogates, U+2028/U+2029, and U+FFFE/U+FFFF are rejected. Non-ASCII spacing is not accepted as key/value syntax; NBSP inside a quoted value remains content.
- `name` is lowercase kebab case, at most 64 characters. `description` is nonempty and at most 1024 characters. Whitespace-only values fail.

Use `harness_frontmatter.render(name, description)` for canonical generation: it emits JSON-compatible quoted strings with literal Unicode. A literal emoji is accepted. Escaped surrogate code units such as `"\ud83d\ude00"` are deliberately rejected, paired or unpaired. PyYAML 6.0.1 preserves the two code points in that example, while a JSON decoder can combine them. A literal escaped backslash sequence such as `"\\ud83d"` is ordinary text and remains distinct.

## Installation status and upgrade

The validator and doctor report `installationStatus`, `valid`, `integrityValid`, and `upgradeRequirements`:

| Status | Meaning | CLI exit |
| --- | --- | --- |
| `valid` | All checks pass for a supported v8.0 or v8.1 installation with Artifact Contract 1 | 0 |
| `upgrade-required` | A recognized v7.0–v7.6 Manifest Schema 6 installation passes integrity and applicable legacy checks but lacks the new artifact contract | 2 |
| `invalid` | Malformed content, mismatched hashes/evidence, pending transactions, unsupported metadata, or incomplete Artifact Contract 1 | 1 |

An upgrade requirement never suppresses an integrity error. A supported v8 manifest without its artifact marker or required agent block is invalid. Validation and doctor are read-only, never relabel a v7 installation as compatible with Artifact Contract 1, and never repair files. Runtime-plan validation requires a current compatible artifact contract. Schema 1–5 installations still follow the existing guarded state-migration workflow first; this status classification does not bypass it.

Normal apply independently checks an existing Schema 6 manifest with the same compatibility classifier. It accepts supported current contracts or recognized unversioned v7 legacy provenance, then continues normal ownership/hash checks. Unknown generator versions, missing or invalid current markers (including boolean or float values), and inconsistent legacy/versioned combinations fail before local Git exclusion changes, transaction staging, or managed-file writes. Dry-run and apply report the normal apply error exit code 2. No implicit downgrade or metadata repair is provided. Schema 4/5 regeneration remains a separate pre-existing path; do not apply the Schema 6 classifier indiscriminately to historical formats.

To upgrade a clean installation, rescan evidence, prepare an Authoring Contract 3 draft with current placeholders, materialize, inspect a clean dry-run, apply through the normal hash-checked transaction, and validate again. Do not change only the generator version or artifact marker. Preserve user edits and resolve ownership conflicts explicitly. A second application of the same plan must be a byte- and modification-time-preserving no-op.

## Reproduction and cost claims

The repository includes `tests/fixtures/frontmatter-cases.json` with exact inputs, expected values, and rejection reasons; `tests/frontmatter_differential.py` with the seeded generator and report hashes; and `tests/requirements-validation.txt` pinning the optional test oracle to PyYAML 6.0.1. The normal unit suite remains stdlib-only. Run the differential test inside the `harness` environment:

```shell
conda run -n harness python -m pip install -r tests/requirements-validation.txt
conda run -n harness python tests/frontmatter_differential.py --seed 20260905 --count 11000 --output FRONTMATTER_REPORT.json
```

The report records Python/oracle versions, corpus/generator/input hashes, accepted/rejected counts, mismatches, and surrogate code points. Agreement is limited to the tested accepted subset; it does not establish complete YAML or Unicode compatibility. CI runs this oracle independently on Windows and Linux.

For real upgrade reproduction, extract v7.6 commit `d91f0a5ae261d44c86f4082ba5098d55b7e5cc4c` or v8.0 commit `ed2972555562c736496e8d90463f52efabf05305` to a separate baseline source directory and run `conda run -n harness python tests/verify_release_upgrade.py --baseline BASELINE_SOURCE --output UPGRADE_REPORT.json` from the v8.1 source tree. This uses the old generator to create installations in disposable directories, then checks read-only diagnosis, a clean upgrade, a repeated no-op, preservation of external edits, and static instruction-size deltas. A v7.6 installation initially requires upgrade; a clean v8.0 installation remains valid. The source trees must include their test fixtures; the script does not contact Git remotes.

Instruction characters and UTF-8 bytes are static measurements. Loaded context, token counters, repeated work, latency, and billing require separate execution observations with explicit coverage. An unchanged agent count proves neither unchanged cost nor token savings. This release adds no agents by default and claims no measured live efficiency improvement or scRAE benchmark result.
