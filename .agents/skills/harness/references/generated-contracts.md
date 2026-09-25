# Generated artifact contracts

The current Harness for Codex preserves Authoring Contract 3 drafts, Artifact Contract 2 plans, and Manifest Schema 7 installations from v9.0. The project-local workspace contract remains unchanged. Plan Schema 3, Transaction Schema 2, runtime-plan Schema 1, and Evaluation Schema 2 also remain unchanged.

Apply validates the incoming plan and independently classifies the existing installation. Releases explicitly listed in `harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS` are compatible with Schema 7, `project-local` scope, Artifact Contract 2, and `not-managed` Git protection with no patterns. Recognized v7/v8 installs require a reviewed workspace upgrade; future version compatibility is never inferred from ordering or prefixes.

Git authorization advice is added during new materialization outside the required canonical blocks. Existing v9.0 plans and installations remain valid without it. Updating the installer or generator does not automatically update project artifacts or establish runtime authorization enforcement; see [git-authorization.md](git-authorization.md).

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
| `valid` | All checks pass for an explicitly compatible Schema 7 / project-local / Artifact Contract 2 installation | 0 |
| `upgrade-required` | Recognized v7.0–v7.6 Schema 6 without an artifact marker, or v8.0/v8.1 Schema 6 with Artifact Contract 1, passes legacy integrity checks | 2 |
| `invalid` | Corruption, mismatched hashes/evidence, pending transactions, unsupported combinations, or incomplete required contracts | 1 |

An upgrade requirement never suppresses an integrity error. A v8 installation still requires Artifact Contract 1 and its canonical agent blocks; neither is waived because a workspace upgrade is pending. Validation and doctor never relabel legacy files or repair them. Runtime plans require current compatible installation state. Schema 1–5 installations follow the separate guarded state-migration and reviewed-regeneration workflow.

Normal apply independently checks Schema 6/7 manifests with the same compatibility classifier before transaction staging or managed-file writes. Known legacy provenance may proceed through ownership/hash checks; unknown versions, inconsistent schema/scope/contract combinations, missing markers, booleans, and float markers fail. Dry-run and apply use normal error exit code 2. No implicit downgrade or version-field repair is supported; Schema 4/5 regeneration remains separate.

To upgrade a clean installation, rescan evidence, prepare an Authoring Contract 3 draft with current placeholders, materialize, inspect a clean dry-run, apply through the normal hash-checked transaction, and validate again. Do not change only the generator version or artifact marker. Preserve user edits and resolve ownership conflicts explicitly. A second application of the same plan must be a byte- and modification-time-preserving no-op.

## Reproduction and cost claims

The repository includes `test/fixtures/frontmatter-cases.json` with exact inputs, expected values, and rejection reasons; `test/integration/frontmatter_differential.py` with the seeded generator and report hashes; and `test/requirements-validation.txt` pinning the optional test oracle to PyYAML 6.0.1. The normal unit suite remains stdlib-only. Run the differential test inside the `harness` environment:

```shell
conda run -n harness python -m pip install -r test/requirements-validation.txt
conda run -n harness python test/integration/frontmatter_differential.py --seed 20260905 --count 11000 --output FRONTMATTER_REPORT.json
```

The report records Python/oracle versions, corpus/generator/input hashes, accepted/rejected counts, mismatches, and surrogate code points. Agreement is limited to the tested accepted subset; it does not establish complete YAML or Unicode compatibility. Current CI runs this oracle on Linux. Windows release validation is paused.

For real upgrade reproduction, use `test/integration/prepare_release_baselines.py` to materialize the immediately preceding release, then run `test/integration/verify_release_upgrade.py --baseline BASELINE_SOURCE --output UPGRADE_REPORT.json`. The prior generator creates a real installation; current tools check compatibility, clean update, repeated no-op, user-edit preservation and static instruction-size deltas. Older contract regressions remain in focused unit fixtures; do not recreate the complete historical source matrix.

Instruction characters and UTF-8 bytes are static measurements. Loaded context, token counters, repeated work, latency, and billing require separate execution observations with explicit coverage. An unchanged agent count proves neither unchanged cost nor token savings. This release adds no agents by default and claims no measured live efficiency improvement or scRAE benchmark result.

For independent installer permission comparison, use `test/integration/verify_installer_permissions.py --baseline BASELINE_SOURCE --candidate . --output PERMISSIONS_REPORT.json` with the same immediately preceding release. POSIX checks cover source hashes, modes, dry-run/no-op behavior and user-file metadata. Windows mode bits do not substitute for Linux permission validation.
