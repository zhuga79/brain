from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import brain_task_parser

from brain_core import atomic, taskfile

SUBTASKS_RE = re.compile(r"^## Subtasks\s*$(.+?)(?=^## |\Z)", re.S | re.M)
STATUS_RE = re.compile(r"^status:\s*\S+\s*$", re.M)


class PRDError(RuntimeError):
    """PRD commit cannot proceed because the source or queue state is invalid."""


@dataclass(frozen=True)
class NormalizedSubtask:
    prio: str
    task_id: str
    title: str
    block: str


@dataclass(frozen=True)
class CommitResult:
    parent_id: str
    subtasks: list[NormalizedSubtask]
    appended_ids: list[str]
    recovered: bool
    changed: bool


def _read(path: Path) -> str:
    return atomic.read_text(path) if path.exists() else ""


def _write_prd(path: Path, text: str) -> None:
    atomic.write_text(path, text, prefix=".prdfile.")


def _extract_subtasks(prd_text: str) -> str:
    match = SUBTASKS_RE.search(prd_text)
    if not match:
        raise PRDError("no ## Subtasks section in PRD")
    return match.group(1)


def normalize_subtasks(parent_id: str, sub_text: str) -> list[NormalizedSubtask]:
    blocks = brain_task_parser.find_blocks(sub_text)
    if not blocks:
        raise PRDError("no subtasks found")

    normalized: list[tuple[str, str, str, str, dict[str, object]]] = []
    local_to_full: dict[str, str] = {}
    seen_full_ids: set[str] = set()
    duplicate_full_ids: set[str] = set()

    for block in blocks:
        parsed = brain_task_parser.parse_block(block)
        if not parsed:
            # t-2026-08-14-prd-malformed-subtask-rejectio: a block that
            # find_blocks() matched but parse_block() could not read used to
            # be dropped silently here, so the rest of the PRD committed
            # while this one vanished from PRD, active.md and the log alike.
            # Reject the whole batch instead — mirrors what `brain-prd
            # dry-run` already does for the same input. Only the header line
            # is echoed back, never the block body, so any secret pasted
            # into a continuation line does not leak into the error.
            raise PRDError(f"invalid subtask header: {block.splitlines()[0]}")
        prio = str(parsed["prio"])
        local_id = str(parsed["id"])
        title = str(parsed["title"])
        full_id = local_id if local_id.startswith("t-") else f"{parent_id}-{local_id}"
        if full_id in seen_full_ids:
            duplicate_full_ids.add(full_id)
        seen_full_ids.add(full_id)
        local_to_full[local_id] = full_id
        normalized.append((prio, full_id, title, block, parsed))

    if not normalized:
        raise PRDError("no subtasks found")
    if duplicate_full_ids:
        raise PRDError(
            "duplicate normalized PRD subtask ids: " + ", ".join(sorted(duplicate_full_ids))
        )

    out: list[NormalizedSubtask] = []
    for prio, full_id, title, original, _parsed in normalized:
        body_lines = original.splitlines()[1:]
        new_body: list[str] = []
        for line in body_lines:
            new_body.append(
                re.sub(
                    r"depends_on: *\[([^\]]*)\]",
                    lambda mm: "depends_on: [" + ", ".join(
                        local_to_full.get(dep.strip(), dep.strip())
                        for dep in mm.group(1).split(",")
                        if dep.strip()
                    ) + "]",
                    line,
                )
            )
        if not any("parent:" in line for line in new_body):
            new_body.insert(0, f"      parent: {parent_id}")
        out.append(NormalizedSubtask(prio, full_id, title, f"- [ ] [{prio}] {full_id} — {title}\n" + "\n".join(new_body)))
    return out


def replace_subtasks_section(prd_text: str, blocks: list[str], *, status: str | None = None) -> str:
    replacement = "## Subtasks\n\n" + "\n\n".join(blocks)
    if SUBTASKS_RE.search(prd_text):
        updated = SUBTASKS_RE.sub(replacement, prd_text, count=1)
    else:
        tail = "" if prd_text.endswith("\n") else "\n"
        updated = prd_text + tail + "\n" + replacement
    if status is None:
        return updated
    if STATUS_RE.search(updated):
        return STATUS_RE.sub(f"status: {status}", updated, count=1)
    return updated


def normalize_prepared_blocks(parent_id: str, blocks: list[str]) -> list[NormalizedSubtask]:
    return normalize_subtasks(parent_id, "\n\n".join(blocks))


def _queue_counts(*texts: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for text in texts:
        for block in brain_task_parser.find_blocks(text):
            parsed = brain_task_parser.parse_block(block)
            if not parsed:
                continue
            task_id = str(parsed["id"])
            counts[task_id] = counts.get(task_id, 0) + 1
    return counts


def _append_blocks(active_text: str, parent_id: str, blocks: list[str]) -> str:
    if not blocks:
        return active_text
    header = f"## PRD subtasks of {parent_id}"
    body = "\n\n".join(blocks)
    if header in active_text:
        pattern = re.compile(rf"(^## PRD subtasks of {re.escape(parent_id)}\s*$.*?)(?=^## |\Z)", re.M | re.S)
        match = pattern.search(active_text)
        if match:
            section = match.group(1).rstrip()
            updated = section + "\n\n" + body + "\n"
            return active_text[:match.start()] + updated + active_text[match.end():]
    prefix = active_text.rstrip()
    if prefix:
        prefix += "\n\n"
    return prefix + header + "\n\n" + body + "\n"


def _commit_locked(
    prd_path: Path,
    active_path: Path,
    done_path: Path,
    parent_id: str,
    prd_text: str,
    subtasks: list[NormalizedSubtask],
) -> CommitResult:
    expected_ids = [item.task_id for item in subtasks]

    active_text = _read(active_path) or "# Active tasks\n"
    done_text = _read(done_path)
    counts = _queue_counts(active_text, done_text)
    duplicates = [task_id for task_id in expected_ids if counts.get(task_id, 0) > 1]
    if duplicates:
        raise PRDError(f"duplicate PRD subtasks in queue: {', '.join(sorted(duplicates))}")

    missing_ids = [task_id for task_id in expected_ids if counts.get(task_id, 0) == 0]
    missing_blocks = [item.block for item in subtasks if item.task_id in missing_ids]

    committed = bool(re.search(r"^status:\s*committed\s*$", prd_text, re.M))
    recovered = committed != (not missing_ids)
    changed = False

    committed_text = replace_subtasks_section(prd_text, [item.block for item in subtasks], status="committed")

    if missing_blocks:
        taskfile.atomic_write(active_path, _append_blocks(active_text, parent_id, missing_blocks))
        changed = True

    if committed_text != prd_text:
        _write_prd(prd_path, committed_text)
        changed = True

    return CommitResult(
        parent_id=parent_id,
        subtasks=subtasks,
        appended_ids=missing_ids,
        recovered=recovered,
        changed=changed,
    )


def commit(prd_path: Path, active_path: Path, done_path: Path, parent_id: str) -> CommitResult:
    tasks_dir = active_path.parent
    with taskfile.queue_lock(tasks_dir):
        prd_text = _read(prd_path)
        if not prd_text:
            raise PRDError(f"no PRD at {prd_path}")
        subtasks = normalize_subtasks(parent_id, _extract_subtasks(prd_text))
        return _commit_locked(prd_path, active_path, done_path, parent_id, prd_text, subtasks)


def commit_prepared(
    prd_path: Path,
    active_path: Path,
    done_path: Path,
    parent_id: str,
    prepared_blocks: list[str],
) -> CommitResult:
    tasks_dir = active_path.parent
    with taskfile.queue_lock(tasks_dir):
        prd_text = _read(prd_path)
        if not prd_text:
            raise PRDError(f"no PRD at {prd_path}")
        subtasks = normalize_prepared_blocks(parent_id, prepared_blocks)
        return _commit_locked(prd_path, active_path, done_path, parent_id, prd_text, subtasks)
