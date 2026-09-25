# Review changed producer/consumer contracts

Read when a task changes an interface, persisted state, lifecycle transition or cross-component data flow. A local cosmetic edit does not require this procedure or a separate reviewer. Use the existing task/revision budget and native delegation only when it adds value.

## Trace the smallest affected slice

Identify the changed producer, at least one actual consumer, the shared contract and the check that can demonstrate compatibility. Prefer precise symbol/caller searches or available Graft retrieval, then inspect the returned source. A search hit or index is navigation evidence, not proof of current behavior. Extend the slice only when an observed dependency requires it.

| Changed boundary | Compare both sides | Useful failure probe |
| --- | --- | --- |
| API, event or command | names, required/optional fields, types, nullability, units, errors and defaults against actual callers | missing/old field, rejected input, alternate error shape |
| DB/file schema to API to display | schema/migration, serialization and consumer assumptions | old stored record, partial migration, absent value |
| State/lifecycle | allowed transitions and terminal states against every writer and recovery path | retry, interruption, duplicate event or stale completion |
| Route/resource ownership | declared route/identifier against generated links and lookups | renamed/deleted endpoint or resource |
| Model/data interface | shape, axis/feature order, dtype, preprocessing and checkpoint metadata | reordered features, incompatible checkpoint or evaluator space |
| Distributed/concurrent work | ownership generation and result identity against integration/timeout behavior | late result, superseded attempt or active prior writer |

Do not silently take write ownership of another component. If a matching consumer must change, extend the authorized task scope explicitly within the user's request or report the incompatibility. A boundary does not automatically justify an additional permanent agent.

## Verify incrementally, then integrate

Use an existing focused check at the first complete producer/consumer slice so a mismatch is caught before unrelated work accumulates. Run broader integration once when the combined change needs it; do not repeat a full suite after every file. After subsequent edits, invalidate affected earlier results and reuse only checks whose inputs and assumptions remain unchanged.

Record the actual command/check, outcome, checked contract and missing coverage. A reviewer saying “looks good,” a valid manifest, or an unchanged hash cannot establish runtime compatibility. A blocker should include its failing example and affected consumer. Stop after the bounded revision budget or repeated failure without new evidence.
