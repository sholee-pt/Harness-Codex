# Project Analysis

Read this reference when profiling a new repository or when its structure has materially changed.

## Evidence order

Inspect high-signal sources before sampling implementation files:

1. repository instructions and top-level documentation;
2. package, workspace, build, and dependency manifests;
3. application entry points and public interfaces;
4. tests, CI workflows, schema or migration files;
5. representative files from each candidate boundary.

Do not read secret values, generated dependency trees, build outputs, or large datasets. File names may be inventoried, but sensitive files should not be opened unless the user explicitly places them in scope.

## Boundary model

Describe the project through observable boundaries rather than language labels alone:

- **Responsibility:** separately owned business or technical capability.
- **Execution environment:** browser, server, worker, mobile runtime, CLI, build system, or data job.
- **Contract:** API, schema, event, file format, package interface, or command interface.
- **Data flow:** collection, transformation, persistence, analysis, and presentation stages.
- **Quality risk:** security boundary, irreversible state change, compatibility surface, or expensive verification.
- **Workflow:** repeated sequence that benefits from a stable procedure.

A frontend/backend split is one possible contract boundary, not a default architecture.

## Evidence record

For each proposed boundary, capture:

- concise boundary name;
- supporting paths or configuration;
- inputs and outputs;
- dependencies on other boundaries;
- recurring work it receives;
- failure impact and applicable verification.

Do not infer an agent merely because a directory or framework exists. A boundary must lead to materially different expertise, independent work, context isolation, reuse, or a quality contract.

## Profile outcome

Produce a short project summary, an evidence-backed boundary list, and explicit uncertainty. If the evidence does not justify multiple roles, say so and keep the topology minimal.
