# Transaction Recovery

Read this reference when status or apply reports `.harness/transaction.json`.

## Lifecycle

1. Harness revalidates every managed hash, full target hash, and create-path absence.
2. It atomically writes a `preparing` journal before creating staging or backup files.
3. It writes desired outputs under `.harness/transactions/<id>/staged/`, copies update targets under `backups/`, and marks the journal `prepared`.
4. It replaces create and update targets, recording progress after each replacement.
5. It replaces `.harness/manifest.json` last, marks the transaction `committed`, and removes the journal workspace.

An ordinary write error triggers rollback in the same process. A process termination, machine restart, or cleanup failure may leave the journal for the next run.

A `preparing` journal means target mutation never began. Recovery removes only that transaction's staging and backup workspace.

## Recovery

Run:

```shell
conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <repo-root> --recover
```

Recovery does not trust only the recorded applied-path list. It checks every operation against the original and desired hashes, so it also handles a termination after target replacement but before the progress marker was written.

- An unchanged original is left in place.
- A transaction-created file matching the staged hash is removed.
- An updated target matching the staged hash is restored from its verified backup.
- A missing updated target is treated as an external deletion and preserved as a recovery conflict.
- A target with any other hash is treated as an external edit and is preserved.

Recovery validates all operations before restoring or removing any target. If one target conflicts, no recovery mutation begins and the journal remains available for inspection.

Inspect the current state without mutation:

```shell
conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <repo-root> --inspect-transaction
```

## Orphaned staging workspace

If `.harness/transactions/` exists without `.harness/transaction.json`, normal hash-based recovery is impossible because no journal identifies intended targets. Inspect first. If the output confirms `orphaned-workspace` and the contents are disposable staging data, remove only that reserved workspace with:

```shell
conda run -n harness python <harness-skill-root>/scripts/harness_apply.py --root <repo-root> --clean-orphaned-transaction
```

This command refuses to run when a journal exists and does not modify generated target files.

## Manual conflict handling

Do not delete the journal or transaction directory to bypass a conflict. Preserve the external edit separately, then restore the conflicted target to either the recorded original content or the staged transaction content. Run `--recover` again and confirm that status reports no transaction before generating another plan.
