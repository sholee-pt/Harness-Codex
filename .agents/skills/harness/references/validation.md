# Validation

Read this reference after artifacts have been generated or updated.

## Structural checks

- Agent TOML parses and contains `name`, `description`, and `developer_instructions`.
- Every skill has valid frontmatter and a directory-matching name.
- Manifest paths stay inside the repository and all topology references resolve.
- The root instruction file has at most one complete managed block.
- Managed hashes match after generation.
- Generated files contain no Claude-only or obsolete Agent Teams primitives.

## Behavioral scenarios

Test the applicable cases, using an isolated temporary repository when possible:

1. A small single-boundary project produces no unnecessary specialist agent.
2. A composite project is divided by real responsibility, runtime, data, or contract boundaries.
3. A non-layered research, data, documentation, library, or CLI project does not acquire frontend/backend roles.
4. A same-language monorepo is divided only when package responsibilities justify it.
5. Existing root instructions survive managed-block insertion.
6. A user-modified managed file is preserved and reported.
7. A second run over unchanged inputs produces no diff.
8. Missing tools, post-freeze mutation, and non-retryable failures are surfaced.

## Completion gate

Validation succeeds only when every planned artifact is accounted for and structural checks pass. Clearly separate structural validation from a live Codex discovery or delegation smoke test, which may require restarting the session.
