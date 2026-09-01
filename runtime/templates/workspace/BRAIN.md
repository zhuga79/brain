# <Project Name>

> One-line purpose: what this project is and who it is for. This first H1 and
> line become the project's dashboard tab label and subtitle, so make it
> specific (e.g. "Acme Billing API", not "Workspace").

- **created:** <YYYY-MM-DD>
- **status:** active
- **primary role:** developer

## Purpose

Describe what this folder is for in one or two sentences.

## Structure

- `sources/` or `raw/` - source materials; agents must not edit unless explicitly allowed.
- `_work/` - drafts and intermediate work.
- `_final/` - current final documents.
- `_archive/` - old material kept for reference.

## Agent Rules

- Read this file before changing anything in this folder.
- Keep changes inside this folder unless the user explicitly names another path.
- Do not delete, move or rename source materials without explicit approval.
- Record substantial work in `LOG.md` when it exists.
- Use `TASKS.md` when local tasks exist.
- After copying this template, walk the live Brain role catalog (`roles/*.md`) and classify every role into Role Policy (`core` / `available` / `gated`) or leave it unlisted (blocked by default). Record that pass under Role Catalog Review. The lists below are a starter, not a finished policy. Do not copy `roles/` into this folder.

## Allowed Roles

- developer
- researcher
- reviewer

## Workspace Profile

type: docs
primary_role: developer

## Role Policy

core:
- developer

available:
- researcher
- reviewer

gated:
- lawyer
- accountant
- tax-advisor
- compliance

blocked:
- none

## Role Catalog Review

reviewed: <YYYY-MM-DD>
catalog: <BRAIN_SYSTEM_PATH>/roles
not used (blocked by default):
- <role from the catalog that does not apply here>

## Action Gates

requires_user_approval:
- sending emails or messages
- changing signed or final documents
- moving, renaming or deleting source materials
- legal conclusions intended for external use
- tax conclusions intended for external use

## Sensitive Zones

- `sources/`
- `raw/`
- `credentials/`
- `.env`

## Done Checks

- Outputs are saved in the agreed folder.
- Local task acceptance is satisfied.
- Substantial changes are logged.
