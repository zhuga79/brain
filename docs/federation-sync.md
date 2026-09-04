---
title: Federation and Sync
type: concept
created: 2026-05-16
updated: 2026-09-04
curation: agent
protected: false
source_policy: advisory
tags: [federation, sync]
sources: []
related: [architecture-overview, decision-multi-user-federation, deb-install-runbook]
visibility: public
---

# Federation and Synchronization

Federation lets two or more people work against one shared git repository of a
vault (`~/brain`) without losing data. It is **advisory, not a distributed
lock protocol**: nodes name themselves, git carries the state, and the merge
rules below make a concurrent cycle converge instead of clobbering.

Everything runs through `brain-federation` (`runtime/bin/brain-federation`):
`support`, `preflight`, `plan`, `import-tasks`, `write-wiki-proposals`,
`tasks-check`, `sync`, `merge-tasks`, `merge-log`.

## Node identity

Each vault names itself. `brain_federation.core.node_id(brain)` resolves, in
order:

1. `$BRAIN_NODE_ID` — explicit operator override.
2. `<brain>/config/federation.json` → `"node_id"`.
3. git `user.email` — **only** when opted in
   (`$BRAIN_NODE_ID_FROM_GIT=1` or `"node_id_from_git": true` in
   `federation.json`). Off by default: the email is operator PII that would
   otherwise ride every synced journal row.
4. `"anonymous"` — deterministic fallback, so a single-user vault with no
   federation config keeps working and leaks nothing.

The value feeds the `node=…` field of `wiki/log.md` audit rows. A configured
identity that would break the journal line format (a newline, a `|`) raises
`ValueError` rather than falling back silently. `config/federation.json` and
`BRAIN_NODE_ID` are not synchronised — identity is per node.

## Lock conflict is surfaced, never resolved

`brain-lock acquire` refuses a task that already stands `[~]` in the
synchronised `tasks/active.md` with another node's id and a fresh timestamp
(inside TTL). `brain-federation preflight` emits `federated-lock-warning`
(severity `review`) when a task the local vault holds a lock on has changed on
the remote side. `import-tasks`/`plan` mark a remote `[~]` as a blocking
`task-imported-in-progress` naming the holding node. Downgrading `[~]` → `[ ]`
needs an explicit review flag — the system never does it on its own.

## Deterministic `wiki/log.md` merge

`wiki/log.md` is append-only, so a rebase conflict on it is spurious. A git
merge driver, `brain-log`, is installed by `brain-federation sync` (into
`.git/info/attributes` and `merge.brain-log.driver`). It parses both sides
into journal rows, takes the commutative union, drops rows with an identical
`(ts, op, task_id, agent, node, extra)` identity, and re-emits them in a
deterministic order (epoch, then the tuple, then raw text). `merge_journal()`
is the pure function; `brain-federation merge-log` exposes it for a manual
`git merge-file`-style call.

## Task-queue merge on sync

When `git pull --rebase` inside `brain-federation sync` conflicts on
`tasks/active.md` or `tasks/done.md`, `finish_rebase_auto_resolve` merges by
**task id**, not by line position:

- a task present on only one side is kept — federation never drops a task;
- when both sides changed the state, the higher rank wins
  (`x` > `~` > `!` > open); a tie goes to the side that changed from the base;
- a one-sided edit to `title`, `role`, `mode` or `acceptance` is taken.

Two situations are **not** auto-merged — they block the sync and abort the
rebase with a clean tree, emitting `federation-sync-queue-conflict`:

- **field-divergence** — both sides changed `title`/`role`/`mode`/`acceptance`
  away from the base, differently;
- **active-done-split** — the task is open on one side and done on the other.

The journal driver and the queue merge run in the same rebase loop, so one
`brain-federation sync` converges both files or blocks with a diagnostic.

## The sync flow

`brain-federation sync [--repo <path>] [--brain <path>]`:

1. validate `node_id`; install the `brain-log` merge driver;
2. `git pull --rebase`. On conflict, `finish_rebase_auto_resolve` resolves the
   journal and the queue and continues the rebase; a hard divergence aborts
   the rebase and blocks;
3. `git push`;
4. append a local (unpushed) `federation-sync … status=ok` row to
   `wiki/log.md`.

`brain-sync-cycle --apply` wraps this for the systemd timer: it auto-commits
journal-only dirt first, refuses to sync when preflight has a blocking
finding, and re-commits the journal afterwards.

## What never synchronises

`.locks/`, `.brain/`, `.provider-health.json`, `handoff/ORCHESTRATOR_HANDOFF.md`
and `wiki/_views/` are runtime-local. `preflight` flags any of them that would
actually reach a peer (tracked in the index, staged, or present and not
git-ignored) as a blocking `runtime-file-included`.
