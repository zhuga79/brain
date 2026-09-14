# Brain

[![tests](https://github.com/Blqd/brain/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/Blqd/brain/actions/workflows/tests.yml)

File-backed memory and task orchestration for humans and LLM agents sharing
one vault. Not a framework and not a service: a set of CLIs over plain
markdown files and git. There is no daemon, no database, nothing to host — the
whole state is files, and therefore diffable, forkable, and mergeable.

Works with any agentic CLI — `claude`, `codex`, `gemini`, `opencode`. An agent
gets a role, reads its persona, and picks a task from a shared queue. A small
group (2–5 people) can work the same vault over git without losing data.

The approach builds on the [LLM wiki idea][llm-wiki] by Andrej Karpathy:
have the agent maintain a wiki instead of re-deriving knowledge from scratch in
every session. Brain takes that insight and adds the operational layer a team
needs — roles, locks, reviews, and federation.

[llm-wiki]: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

---

## Why

A typical LLM session loses everything when the window closes. Knowledge
dissolves in the chat, decisions are re-made from scratch, and two agents
running in parallel overwrite each other's work. With a small team of several
people — each running their own agents — it gets worse: a task nobody owns,
a decision made in one session that never reaches another, a queue that forks
silently.

Brain solves this with four things:

- **Knowledge lives in files**, not in model context. `wiki/` is what has
  been figured out; `raw/` is immutable sources; `tasks/` is the work queue.
- **An agent has a role.** An architect doesn't write code, a reviewer doesn't
  make architectural decisions, a tax advisor doesn't draft contracts. A role
  is a persona, constraints, and a list of permitted operations.
- **Work is locked.** Before picking a task, an agent requests a lock with
  TTL. A crashed agent releases the task automatically.
- **The vault syncs over git.** Two or more people share one repository; the
  state is merged deterministically, and nothing is lost on a collision.

---

## Federation: a group sharing one task list

Federation is the multi-user mode. It lets 2–5 people (plus their agents) work
on one shared git repository of the vault without clobbering each other.

- **Node identity.** Each vault names itself (`BRAIN_NODE_ID` or
  `config/federation.json`), and the name rides every audit row in
  `wiki/log.md`. Falls back to `anonymous` so a single-user vault leaks nothing.
- **Deterministic journal merge.** `wiki/log.md` is append-only; `brain-federation`
  installs a git merge driver that takes the commutative union of rows and
  deduplicates by `(ts, op, task_id, agent, node, extra)`.
- **Queue merge by task id, not line position.** When two nodes edit
  `tasks/active.md`, progress wins (`done` > `in-progress` > `blocked` > open),
  a one-sided field edit is taken, and no task is ever dropped. Real
  divergence (two conflicting edits, or open-vs-done on the same task) blocks
  the sync with a clean abort instead of a silent clobber.
- **Lock conflicts are surfaced, never resolved silently.** Acquiring a task
  held fresh by another node is refused; downgrading a remote `in-progress`
  needs an explicit review decision.

```bash
brain-federation preflight   # what would sync break?
brain-federation sync        # pull --rebase with the merge drivers, push
brain-sync-cycle --apply     # the same, driven by a systemd timer
```

Federation is advisory, not a distributed lock protocol: git carries the state
and the merge rules make a concurrent cycle converge. That is a deliberate
trade-off for a small team on one repository.

---

## Brain vs. the alternatives

There are several orchestration projects in the same space. The differences
matter more than the overlap.

| | **Brain** | **OpenClaw** | **ai-crew-sync** | **ShareClaw** |
|---|---|---|---|---|
| State lives in | **git + markdown only** | daemon + database | Postgres server | JSON + SQLite |
| Something to run/host | **no daemon, no server** | daemon | server (Postgres) | none (but DB files) |
| Works with | **any agentic CLI** | wraps CLIs as its engine | any MCP client | any file-based agent |
| Multi-user | **git federation, 2–5 people** | single-operator focus | shared bus (server) | same filesystem only |
| Task lock | mkdir-based lock, TTL | session/wt ownership | lease, TTL | file lock |
| Reviewers forced to use a **different model provider** | **yes** | no | no | no |
| Council = independent opinions, synthesis by a **different** model | **yes** | consensus voting | no | consensus voting |
| Human-curated content outranks sources (`curation: human` / `protected`) | **yes** | no | no | no |
| Purpose | durable shared task list + memory | run coding CLIs as one engine | team coordination bus | agent-swarm coordination layer |

The short version:

- **OpenClaw** solves "drive several coding CLIs as one runtime". Brain doesn't
  wrap CLIs at all — it coordinates the agents you already run, and its contract
  is files.
- **ai-crew-sync** needs a server and a database for the same coordination.
  Brain's coordination *is* the git repo you already trust.
- **ShareClaw** is the closest in spirit (file-based coordination layer), but
  keeps its truth in JSON and SQLite. Brain keeps everything in git, so the
  state syncs, forks, and merges like source code — and two vaults converge
  deterministically instead of clobbering.

If hosting a daemon and a database is fine for your team, ai-crew-sync or
OpenClaw may fit better. If you want the shared task list to be a folder in
your repository — with no service to run, no state that is not in git, and
review that does not use the same model that wrote the code — Brain is the
different shape.

---

## Two repositories

System and data live in separate repositories. The boundary is structural:
a private file cannot end up here because its directory doesn't exist in this
repo.

| Repository | Contents | Location |
|---|---|---|
| System (this repo) | `runtime/`, `tests/`, `spec/`, `roles/`, `teams/`, `doctrine/`, `skills/`, ADR, root documents | `github.com/Blqd/brain` |
| Data | layer: `wiki/`, `tasks/`, `raw/`, `council/`, `handoff/`, `prd/`, `.locks/` | `~/brain`, one per operator / shared per team |

The system checkout is this repository. The data layer is the operator's
(team's) private tree. If `BRAIN_SYSTEM_PATH` is not set, both layers are
looked up in a single root (legacy mode). `roles/` belongs to the system
checkout: a role file lives at `roles/<role>.md` in its checkout; listing is
done via `brain-doctrine roles`. The data root must not contain `roles/`.

Editing `runtime/`, `roles/`, `tests/`, or `spec/` means a branch in the
system checkout, not a commit in `~/brain`. Pre-commit and `brain-validate`
reject such staged files in the data tree. To apply to a live instance:
`brain-ops update` (`git pull` + install + `tests/run.sh`).

---

## Installation

```bash
git clone https://github.com/Blqd/brain.git ~/src/brain
cd ~/src/brain
./setup-brain-v2.sh
export BRAIN_PATH="$HOME/brain"
export BRAIN_SYSTEM_PATH="$HOME/src/brain"
```

The script installs CLIs into `~/.local/bin` and creates the data tree at
`~/brain` if it doesn't exist. Roles resolve from
`$BRAIN_SYSTEM_PATH/roles/<role>.md`; listing via `brain-doctrine roles`.
A Debian package builds via `runtime/packaging/build-deb.sh` (see
`docs/deb-install-runbook.md`).

CLIs are **copied**, not symlinked: after `git pull` you need a reinstall
for changes in `runtime/bin/` to take effect. Both operations plus tests are
covered by a single command:

```bash
brain-ops update
```

### Key commands

| Command | What it does |
|---|---|
| `brain-task` | queue: next, take, complete, block |
| `brain-lock` | TTL-based locks |
| `brain-council` | start and synthesize council sessions |
| `brain-federation` | multi-user sync: preflight, plan, sync, merge-tasks, merge-log |
| `brain-orchestrator` | run an agent on a task with quota-exhaustion fallback |
| `brain-search` | BM25 search over machine cache |
| `brain-validate` | wiki integrity and curation contracts |
| `brain-lint` | duplicates, orphan pages, logical errors |
| `brain-ops update` | `git pull` system checkout + install + tests |

---

## Structure

```
MEMORY.md          constitution: schema, roles, lock protocol
roles/             persona for each role
teams/             named role sets for council mode
doctrine/          responsibility boundaries between roles
runtime/           implementation: lib/ and CLI in bin/
tests/             smoke cases and pytest
docs/decisions/    ADR
```

The data layer (`wiki/`, `raw/`, `tasks/`, `council/`) lives in the data
tree and is not part of this repository.

### Roles

Engineering — `architect`, `developer`, `reviewer`, `security`, `researcher`,
`linter`, `arbiter`. Plus domains for legal, finance, product, and marketing:
`lawyer`, `compliance`, `tax-advisor`, `cfo`, `accountant`, `pm`, `product`,
`strategist`, `designer`, and others.

For `reviewer` and `arbiter`, a **diversification rule** applies: a model
from a different provider than the author's. The same model reviewing itself
makes errors in the same places it writes.

### Council mode

A task spanning multiple responsibility zones is executed not by a single
role. Each role writes an opinion **independently**, without reading
colleagues, then an `arbiter` — a model different from all participants —
synthesizes. This is protection against correlated blind spots, not
bureaucracy.

```bash
brain-council start <task-id>
brain-council synthesize <task-id>
```

---

## Curation contract

Manual human edits in `wiki/` take **priority** over source-derived content.
A page with `curation: human` or `protected: true` is not overwritten by an
agent automatically. Sources in `raw/` are evidence and grounds for
suggestions, not the final word.

---

## PRD mode

Large tasks use `mode: prd`. Taken by `architect`. Workflow:

1. `brain-prd init <task-id>` — creates `~/brain/prd/<id>.md` from a template.
2. Architect fills in the PRD, especially the `## Subtasks` section.
3. `brain-prd commit <id>` — subtasks land in `active.md` with correct
   `depends_on`.
4. `brain-task next --role developer` shows the first available subtask
   (deps already satisfied).
5. When all subtasks are done — closing the parent PRD task.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

The short version: defect reports with reproduction steps and contract
clarifications are the most useful. ADR goes before code when a contract
changes. CLA is not used; inbound=outbound under Apache-2.0.

---

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately via
[GitHub Security Advisories](https://github.com/Blqd/brain/security/advisories/new).

---

## Status

Working software with an active release path: system layer as a public repo,
`.deb` builds on CI, smoke + pytest gates before installs. The tool is
designed for a single operator or a small team (2–5 people) on one shared
vault. Backward compatibility is not guaranteed; some decisions are specific
to a particular workflow. Known weak spots and plans are in
`docs/decisions/decisions-log.md` and ADR pages
`docs/decisions/decision-*.md`.

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0.