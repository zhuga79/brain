"""Federation plan generation and import utilities."""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from brain_core import journal, taskfile

from .core import (
    AGENT_ID_RE,
    SCHEMA_VERSION,
    TASK_ID_RE,
    FEDERATION_CONFIG_FILE,
    Finding,
    brain_path,
    emit,
    exit_code,
    has_block,
    node_id,
    node_audit_extra,
    result,
)
from .checks import (
    check_cross_file_conflicts,
    check_duplicates,
)
from .git_ops import (
    frontmatter,
    git_run,
    is_git_repo,
)
from .preflight import (
    collect_preflight,
    parse_task_file_optional,
)


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return sha256_text("")


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan_id(data: dict[str, Any]) -> str:
    body = dict(data)
    body.pop("plan_id", None)
    body.pop("generated_at", None)
    return sha256_text(canonical_json(body))


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

def task_refs(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for task in tasks:
        refs.setdefault(task["id"], task)
    return refs


def plan_task_imports(
    repo: Path, brain: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Finding]]:
    repo_active, findings = parse_task_file_optional(repo / "tasks" / "active.md", "repo-active")
    repo_done, repo_done_findings = parse_task_file_optional(repo / "tasks" / "done.md", "repo-done")
    brain_active, brain_active_findings = parse_task_file_optional(
        brain / "tasks" / "active.md",
        "brain-active",
        flag_in_progress=False,
    )
    brain_done, brain_done_findings = parse_task_file_optional(
        brain / "tasks" / "done.md",
        "brain-done",
        flag_in_progress=False,
    )
    findings.extend(repo_done_findings)
    findings.extend(brain_active_findings)
    findings.extend(brain_done_findings)

    findings.extend(check_duplicates(repo_active, "task-duplicate-id"))
    findings.extend(check_duplicates(repo_done, "done-duplicate-id"))
    findings.extend(check_cross_file_conflicts(repo_active, repo_done))
    findings.extend(check_duplicates(repo_active + brain_active, "task-duplicate-id"))
    findings.extend(check_cross_file_conflicts(repo_active, brain_done))
    findings.extend(check_cross_file_conflicts(brain_active, repo_done))

    local_active = task_refs(brain_active)
    local_done = task_refs(brain_done)
    imports: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_remote: set[str] = set()
    for task in repo_active:
        task_id = task["id"]
        item = {
            "id": task_id,
            "title": task["title"],
            "priority": task["priority"],
            "role": task.get("role", ""),
            "mode": task.get("mode", ""),
            "acceptance": task.get("acceptance", ""),
            "source": task.get("source", "repo-active"),
            "path": task.get("path", ""),
            "line": task.get("line", 0),
        }
        if task_id in seen_remote:
            skipped.append({**item, "reason": "duplicate-in-repo"})
            continue
        seen_remote.add(task_id)
        if task["state"] != " ":
            skipped.append({**item, "reason": f"state-{task['state'].strip() or 'open'}"})
            continue
        if task_id in local_active:
            skipped.append({**item, "reason": "already-active"})
            continue
        if task_id in local_done:
            skipped.append({**item, "reason": "already-done"})
            continue
        imports.append({**item, "state": "open"})
    return imports, skipped, findings


# ---------------------------------------------------------------------------
# Source state + plan building
# ---------------------------------------------------------------------------

def git_status(repo: Path) -> list[str]:
    if not is_git_repo(repo):
        return []
    res = git_run(repo, "status", "--porcelain")
    return sorted(line for line in res.stdout.splitlines() if line)


def git_head_sha(repo: Path) -> str:
    if not is_git_repo(repo):
        return ""
    res = git_run(repo, "rev-parse", "HEAD")
    return res.stdout.strip() if res.returncode == 0 else ""


def source_state(repo: Path, brain: Path) -> dict[str, Any]:
    repo_status = git_status(repo)
    return {
        "repo_head": git_head_sha(repo),
        "repo_status": repo_status,
        "repo_status_sha256": sha256_text("\n".join(repo_status)),
        "brain_active": str((brain / "tasks" / "active.md").resolve()),
        "brain_done": str((brain / "tasks" / "done.md").resolve()),
        "brain_active_sha256": sha256_file(brain / "tasks" / "active.md"),
        "brain_done_sha256": sha256_file(brain / "tasks" / "done.md"),
    }


def plan_wiki_changes(
    repo: Path,
    brain: Path,
    changed_paths: set[str],
    findings: list[Finding],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    curation_block_codes = {
        finding.path: finding.code
        for finding in findings
        if finding.code in {"protected-wiki-edit", "human-curated-wiki-edit"}
    }
    proposals: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(changed_paths):
        if not path.startswith("wiki/"):
            continue
        source_path = repo / path
        target_path = brain / path
        target_fm = frontmatter(target_path)
        item = {
            "path": path,
            "source": str(source_path.resolve()),
            "source_sha256": sha256_file(source_path),
            "target_path": str(target_path.resolve()),
            "target_curation": target_fm.get("curation", ""),
            "proposal_only": "true",
        }
        if path in curation_block_codes:
            item["reason"] = curation_block_codes[path]
        proposals.append(item)
    return proposals, skipped


def required_confirmations(findings: list[Finding]) -> list[str]:
    return sorted({finding.code for finding in findings if finding.severity == "review"})


def build_plan(repo: Path, brain: Path) -> tuple[dict[str, Any], list[Finding]]:
    preflight_data, preflight_findings, changed_paths = collect_preflight(repo, brain)
    task_imports, skipped_tasks, task_findings = plan_task_imports(repo, brain)
    findings = preflight_findings + task_findings
    wiki_proposals, skipped_wiki = plan_wiki_changes(repo, brain, changed_paths, findings)
    data = result("plan", repo, brain, findings)
    data["kind"] = "federation-plan"
    data["generated_at"] = utc_now()
    data["generator"] = {
        "tool": "brain-federation",
        "version": "1",
    }
    data["read_only"] = True
    data["write_policy"] = {
        "json": "no writes",
        "out": "writes only the requested plan file",
        "imports": "not performed by plan",
        "wiki": "proposal planning only",
    }
    data["source_state"] = source_state(repo, brain)
    data["preflight"] = preflight_data
    data["task_imports"] = task_imports
    data["skipped_tasks"] = skipped_tasks
    data["wiki_proposals"] = wiki_proposals
    data["skipped_wiki"] = skipped_wiki
    data["required_confirmations"] = required_confirmations(findings)
    data["plan_id"] = plan_id(data)
    return data, findings


# ---------------------------------------------------------------------------
# Plan loading and validation
# ---------------------------------------------------------------------------

def load_plan(path: Path) -> tuple[dict[str, Any] | None, list[Finding], int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [Finding("plan-unreadable", "block", str(path), f"cannot read plan: {exc}")], 2
    except json.JSONDecodeError as exc:
        return None, [Finding("plan-schema-mismatch", "block", str(path), f"invalid plan JSON: {exc}")], 2
    if not isinstance(data, dict):
        return None, [Finding("plan-schema-mismatch", "block", str(path), "plan root must be a JSON object")], 2
    if data.get("schema_version") != SCHEMA_VERSION or data.get("mode") != "plan":
        return data, [Finding("plan-schema-mismatch", "block", str(path), "unsupported plan schema or mode")], 1
    state = data.get("source_state")
    required_state = {"repo_head", "repo_status_sha256", "brain_active_sha256", "brain_done_sha256"}
    if not isinstance(state, dict) or not required_state.issubset(state):
        return data, [Finding("plan-schema-mismatch", "block", str(path), "plan source_state lacks required fingerprints")], 1
    imports = data.get("task_imports")
    if not isinstance(imports, list):
        return data, [Finding("plan-schema-mismatch", "block", str(path), "task_imports must be an array")], 1
    return data, [], 0


def task_import_block(task: dict[str, Any]) -> str:
    role = str(task.get("role") or "developer")
    mode = str(task.get("mode") or "solo")
    source = str(task.get("path") or task.get("source") or "")
    line = str(task.get("line") or "")
    block = (
        f"- [ ] [{task['priority']}] {task['id']} — {task['title']}\n"
        f"      role: {role}   mode: {mode}\n"
        f"      acceptance: {task['acceptance']}\n"
    )
    if source:
        ref = f"{source}:{line}" if line and line != "0" else source
        block += f"      ref: {ref}\n"
    return block


def task_import_validation(imports: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for idx, task in enumerate(imports):
        path = f"task_imports[{idx}]"
        task_id = str(task.get("id", ""))
        if not task_id or not TASK_ID_RE.match(task_id):
            findings.append(Finding("plan-schema-mismatch", "block", path, "task id is missing or invalid"))
        if task_id in seen:
            findings.append(Finding("task-duplicate-id-at-write", "block", path, f"duplicate task id in plan: {task_id}"))
        seen.add(task_id)
        if task.get("state") != "open":
            findings.append(Finding("task-state-not-open", "block", path, f"task {task_id} is not open"))
        for field in ("title", "priority", "acceptance"):
            if not str(task.get(field, "")).strip():
                findings.append(Finding("plan-schema-mismatch", "block", path, f"task {task_id} missing {field}"))
        if str(task.get("priority", "")) not in {"P0", "P1", "P2", "P3"}:
            findings.append(Finding("plan-schema-mismatch", "block", path, f"task {task_id} has invalid priority"))
    return findings


def live_task_conflicts(brain: Path, imports: list[dict[str, Any]]) -> list[Finding]:
    active, active_findings = parse_task_file_optional(
        brain / "tasks" / "active.md", "brain-active", flag_in_progress=False
    )
    done, done_findings = parse_task_file_optional(
        brain / "tasks" / "done.md", "brain-done", flag_in_progress=False
    )
    findings = active_findings + done_findings
    active_by_id = task_refs(active)
    done_by_id = task_refs(done)
    for task in imports:
        task_id = str(task.get("id", ""))
        if task_id in active_by_id:
            findings.append(
                Finding(
                    "task-duplicate-id-at-write",
                    "block",
                    f"{active_by_id[task_id]['path']}:{active_by_id[task_id]['line']}",
                    f"task {task_id} already exists in active.md",
                )
            )
        if task_id in done_by_id:
            findings.append(
                Finding(
                    "task-duplicate-id-at-write",
                    "block",
                    f"{done_by_id[task_id]['path']}:{done_by_id[task_id]['line']}",
                    f"task {task_id} already exists in done.md",
                )
            )
    return findings


def stale_plan_findings(plan: dict[str, Any], args: argparse.Namespace) -> list[Finding]:
    repo = Path(plan.get("repo") or ".").expanduser()
    brain = brain_path(str(plan.get("brain") or ""))
    expected = plan["source_state"]
    current = source_state(repo, brain)
    findings: list[Finding] = []
    comparisons = (
        ("repo_head", args.allow_drift),
        ("repo_status_sha256", args.allow_drift),
        ("brain_active_sha256", False),
        ("brain_done_sha256", False),
    )
    for key, drift_ok in comparisons:
        if expected.get(key) == current.get(key):
            continue
        if args.allow_stale or (drift_ok and args.allow_drift):
            continue
        findings.append(
            Finding(
                "plan-stale",
                "block",
                key,
                f"plan fingerprint mismatch for {key}",
                "regenerate plan or pass an explicit stale/drift override where allowed",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Import lock helpers
#
# t-2026-08-16-federation-import-writes-activ: `.locks/tasks-active` below is
# a *business* lock — it single-flights `brain-federation import-tasks --yes`
# against itself so two concurrent imports don't both compute "not yet
# imported" from the same snapshot, and it gives a readable
# "import lock held by <owner>" error instead of a silent retry. It is
# deliberately NOT the mutex that makes the write to tasks/active.md safe.
#
# That job belongs to `taskfile.queue_lock` (flock on tasks/.taskfile.lock),
# the single mutex every other queue writer (`add`/`take`/`release`/`block`/
# `complete` in brain_core.taskfile, and brain_app.queue / the MCP tool on
# top of it) already serializes through. Before this fix, `append_imports_atomic`
# read tasks/active.md, appended its own entries and replaced the file under
# `.locks/tasks-active` alone — a second, independent mutex over the same
# file. A concurrent `brain-task take` (holding `.taskfile.lock`, not
# `.locks/tasks-active`) could read-modify-write in the same window and the
# last writer's stale in-memory copy would silently clobber the other's
# change: an imported task vanishing, or a `take` transition reverting to
# `[ ]` while its lock directory still claimed the task. Reproduced and
# documented in tests/python/test_brain_federation_plan.py
# (test_append_imports_atomic_race_with_taskfile_take and the reverse
# ordering); see append_imports_atomic below for the fix.
# ---------------------------------------------------------------------------

def acquire_import_lock(brain: Path, agent: str, ttl: int = 600) -> tuple[bool, str]:
    locks = brain / ".locks"
    lock_dir = locks / "tasks-active"
    locks.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    try:
        lock_dir.mkdir()
        (lock_dir / "owner").write_text(f"{agent}|{now}|{ttl}\n", encoding="utf-8")
        return True, ""
    except FileExistsError:
        owner_path = lock_dir / "owner"
        try:
            owner, ts, old_ttl = owner_path.read_text(encoding="utf-8").strip().split("|", 2)
            if now - int(ts) > int(old_ttl):
                for child in lock_dir.iterdir():
                    child.unlink()
                lock_dir.rmdir()
                lock_dir.mkdir()
                (lock_dir / "owner").write_text(f"{agent}|{now}|{ttl}\n", encoding="utf-8")
                return True, ""
            return False, owner
        except (OSError, ValueError):
            return False, "corrupt"


def release_import_lock(brain: Path, agent: str) -> None:
    lock_dir = brain / ".locks" / "tasks-active"
    owner_path = lock_dir / "owner"
    try:
        owner = owner_path.read_text(encoding="utf-8").split("|", 1)[0]
    except OSError:
        return
    if owner != agent:
        return
    try:
        owner_path.unlink()
        lock_dir.rmdir()
    except OSError:
        pass


def append_imports_atomic(brain: Path, imports: list[dict[str, Any]]) -> list[Finding]:
    """Дописать импортированные задачи в active.md под общей блокировкой очереди.

    Пишет под `taskfile.queue_lock` — тем же мьютексом, что `brain_core.taskfile`
    использует для `add`/`take`/`release`/`block`/`complete`. Конфликтная
    проверка (`live_task_conflicts`) переисполняется здесь же, внутри лока: то,
    что было true снаружи (до захвата лока), могло устареть к моменту записи —
    другой писатель мог успеть добавить задачу с тем же id, пока этот вызов
    ждал лок. Возвращает находки: непустой список — конфликт обнаружен под
    локом, запись не выполнена и вызывающий обязан не считать импорт успешным.
    """
    active_path = brain / "tasks" / "active.md"
    with taskfile.queue_lock(active_path.parent):
        findings = live_task_conflicts(brain, imports)
        if findings:
            return findings
        text = (
            active_path.read_text(encoding="utf-8", errors="replace")
            if active_path.exists()
            else "# Active tasks\n"
        )
        text = text.rstrip() + "\n\n"
        text += "\n".join(task_import_block(task).rstrip() for task in imports)
        text += "\n"
        taskfile.atomic_write(active_path, text)
    return []


def log_imports(
    brain: Path,
    agent: str,
    plan_path: Path,
    plan: dict[str, Any],
    imports: list[dict[str, Any]],
) -> None:
    plan_ref = plan.get("plan_id", str(plan_path))
    node = node_id(brain)
    for task in imports:
        journal.append_line(
            journal.format_entry(
                "federation-import-task",
                task["id"],
                agent,
                node_audit_extra(node, f"plan={plan_ref}"),
            ),
            brain,
        )
    journal.append_line(
        journal.format_entry(
            "federation-import-summary",
            "import-tasks",
            agent,
            node_audit_extra(node, f"count={len(imports)} plan={plan_ref}"),
        ),
        brain,
    )


def import_result(
    plan: dict[str, Any] | None,
    plan_path: Path,
    agent: str,
    dry_run: bool,
    findings: list[Finding],
    imported: list[str] | None = None,
) -> dict[str, Any]:
    repo = Path(plan.get("repo") or "") if plan else None
    brain = brain_path(str(plan.get("brain") or "")) if plan else None
    data = result("import-tasks", repo, brain, findings)
    data["plan"] = str(plan_path)
    data["plan_id"] = plan.get("plan_id", "") if plan else ""
    data["agent"] = agent
    data["dry_run"] = dry_run
    imports = plan.get("task_imports", []) if plan else []
    data["would_import"] = len(imports) if isinstance(imports, list) and not has_block(findings) else 0
    data["imported"] = imported or []
    return data


# ---------------------------------------------------------------------------
# Wiki proposal helpers
# ---------------------------------------------------------------------------

CURATION_BLOCKS = {"protected-wiki-edit", "human-curated-wiki-edit"}


def safe_wiki_rel(value: str) -> Path | None:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    if not value.startswith("wiki/") or not value.endswith(".md"):
        return None
    return rel


def proposal_gate_findings(
    plan: dict[str, Any], plan_path: Path, args: argparse.Namespace
) -> list[Finding]:
    findings: list[Finding] = []
    proposal_paths = {
        item.get("path", "") for item in plan.get("wiki_proposals", []) if isinstance(item, dict)
    }
    for finding in plan.get("findings", []):
        if not isinstance(finding, dict):
            continue
        code = str(finding.get("code", ""))
        severity = str(finding.get("severity", ""))
        path = str(finding.get("path", ""))
        if severity == "block" and not (code in CURATION_BLOCKS and path in proposal_paths):
            findings.append(
                Finding(
                    "plan-block-findings",
                    "block",
                    str(plan_path),
                    f"plan contains non-proposal block finding: {code}",
                )
            )
            break
    findings.extend(stale_plan_findings(plan, args))
    return findings


def proposal_result(
    plan: dict[str, Any] | None,
    plan_path: Path,
    agent: str,
    dry_run: bool,
    findings: list[Finding],
    proposal_dir: Path | None = None,
    written: list[str] | None = None,
) -> dict[str, Any]:
    repo = Path(plan.get("repo") or "") if plan else None
    brain = brain_path(str(plan.get("brain") or "")) if plan else None
    data = result("write-wiki-proposals", repo, brain, findings)
    data["plan"] = str(plan_path)
    data["plan_id"] = plan.get("plan_id", "") if plan else ""
    data["agent"] = agent
    data["dry_run"] = dry_run
    proposals = plan.get("wiki_proposals", []) if plan else []
    data["would_write"] = (
        len(proposals) if isinstance(proposals, list) and not has_block(findings) else 0
    )
    data["written"] = written or []
    data["proposal_dir"] = str(proposal_dir) if proposal_dir else ""
    return data


def proposal_meta(brain: Path, rel: Path) -> dict[str, Any]:
    target = brain / rel
    fm = frontmatter(target)
    return {
        "target": str(rel),
        "exists": target.exists(),
        "protected": fm.get("protected", ""),
        "curation": fm.get("curation", ""),
        "source_policy": fm.get("source_policy", ""),
        "target_sha256": sha256_file(target) if target.exists() else "",
    }


def write_proposal_artifacts(
    brain: Path, plan_path: Path, plan: dict[str, Any], agent: str
) -> tuple[Path, list[str], list[Finding]]:
    timestamp = utc_now().replace("-", "").replace(":", "")
    proposal_dir = brain / "proposals" / "federation" / timestamp
    findings: list[Finding] = []
    try:
        proposal_dir.mkdir(parents=True)
    except FileExistsError:
        return proposal_dir, [], [
            Finding("proposal-dir-exists", "block", str(proposal_dir), "proposal directory already exists")
        ]
    except OSError as exc:
        return proposal_dir, [], [
            Finding("proposal-write-failed", "block", str(proposal_dir), f"cannot create proposal dir: {exc}")
        ]

    written: list[str] = []
    manifest_items: list[dict[str, Any]] = []
    for item in plan.get("wiki_proposals", []):
        if not isinstance(item, dict):
            findings.append(
                Finding("plan-schema-mismatch", "block", "wiki_proposals", "proposal item must be an object")
            )
            continue
        rel = safe_wiki_rel(str(item.get("path", "")))
        if rel is None:
            findings.append(
                Finding(
                    "wiki-direct-edit-attempted",
                    "block",
                    str(item.get("path", "")),
                    "proposal target must be wiki/*.md",
                )
            )
            continue
        source = Path(str(item.get("source", ""))).expanduser()
        try:
            proposed_text = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(
                Finding(
                    "proposal-source-unreadable",
                    "block",
                    str(source),
                    f"cannot read proposal source: {exc}",
                )
            )
            continue
        target = brain / rel
        current_text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if current_text == proposed_text:
            continue

        out_md = proposal_dir / rel
        out_diff = out_md.with_name(out_md.name + ".diff")
        out_meta = out_md.with_name(out_md.name + ".meta.json")
        out_md.parent.mkdir(parents=True, exist_ok=True)
        diff_text = "".join(
            difflib.unified_diff(
                current_text.splitlines(keepends=True),
                proposed_text.splitlines(keepends=True),
                fromfile=f"current/{rel}",
                tofile=f"proposal/{rel}",
            )
        )
        out_md.write_text(proposed_text, encoding="utf-8")
        out_diff.write_text(diff_text or "new file\n", encoding="utf-8")
        meta = proposal_meta(brain, rel)
        meta.update(
            {
                "schema_version": SCHEMA_VERSION,
                "source": str(source),
                "source_sha256": sha256_file(source),
                "plan_id": plan.get("plan_id", ""),
            }
        )
        out_meta.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(str(rel))
        manifest_items.append(
            {
                "path": str(rel),
                "markdown": str(out_md.relative_to(proposal_dir)),
                "reason": item.get("reason", ""),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "federation-proposal-manifest",
        "generated_at": utc_now(),
        "agent": agent,
        "plan": str(plan_path),
        "plan_id": plan.get("plan_id", ""),
        "items": manifest_items,
    }
    (proposal_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    journal.append_line(
        journal.format_entry(
            "federation-proposal-batch",
            "write-wiki-proposals",
            agent,
            node_audit_extra(
                node_id(brain),
                f"count={len(written)} plan={plan.get('plan_id', str(plan_path))}",
            ),
        ),
        brain,
    )
    return proposal_dir, written, findings


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    """Handle the `plan` subcommand."""
    repo = Path(args.repo or os.getcwd()).expanduser()
    brain = brain_path(args.brain)
    try:
        data, findings = build_plan(repo, brain)
    except FileNotFoundError as exc:
        print(f"brain-federation plan: unreadable repo path: {exc}", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out).expanduser()
        try:
            out.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"brain-federation plan: cannot write plan: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.out:
        print(f"plan written: {Path(args.out).expanduser()}")
    else:
        emit(data, json_mode=False)
    return exit_code(findings)


def cmd_import_tasks(args: argparse.Namespace) -> int:
    """Handle the `import-tasks` subcommand."""
    plan_path = Path(args.plan).expanduser()
    dry_run = not args.yes
    if not AGENT_ID_RE.match(args.agent):
        findings = [Finding("agent-id-missing", "block", "--as", "valid --as <agent-id> is required")]
        emit(import_result(None, plan_path, args.agent, dry_run, findings), args.json)
        return 1
    plan, findings, rc = load_plan(plan_path)
    if plan is None:
        emit(import_result(None, plan_path, args.agent, dry_run, findings), args.json)
        return rc
    imports = plan.get("task_imports", [])
    findings.extend(task_import_validation(imports))
    if plan.get("summary", {}).get("block", 0):
        findings.append(
            Finding("plan-block-findings", "block", str(plan_path), "plan contains blocking findings")
        )
    if os.environ.get("BRAIN_FEDERATION_IMPORT_DISABLED") == "1":
        findings.append(
            Finding("task-import-disabled", "block", str(plan_path), "task import is disabled by environment")
        )
    findings.extend(stale_plan_findings(plan, args))

    brain = brain_path(str(plan.get("brain") or ""))
    if dry_run:
        if not has_block(findings):
            findings.extend(live_task_conflicts(brain, imports))
        data = import_result(plan, plan_path, args.agent, True, findings)
        emit(data, args.json)
        return exit_code(findings)

    try:
        node_id(brain)
    except ValueError as exc:
        findings.append(Finding(
            "federation-node-invalid", "block", FEDERATION_CONFIG_FILE,
            str(exc),
            "fix the node identity (or $BRAIN_NODE_ID) to a charset-safe value",
        ))
        data = import_result(plan, plan_path, args.agent, False, findings, [])
        emit(data, args.json)
        return exit_code(findings)

    locked = False
    try:
        ok, owner = acquire_import_lock(brain, args.agent)
        if not ok:
            findings.append(
                Finding("task-import-lock-held", "block", "tasks/active.md", f"import lock held by {owner}")
            )
        else:
            locked = True
            if not has_block(findings):
                # Advisory pre-check: cheap, readable error before touching the
                # queue lock. Not authoritative — a writer serialized only by
                # taskfile.queue_lock can still land between this check and the
                # write below, which is why append_imports_atomic re-checks
                # under the lock itself.
                findings.extend(live_task_conflicts(brain, imports))
            if not has_block(findings):
                write_findings = append_imports_atomic(brain, imports)
                findings.extend(write_findings)
                if not write_findings:
                    log_imports(brain, args.agent, plan_path, plan, imports)
        imported = [task["id"] for task in imports] if locked and not has_block(findings) else []
        data = import_result(plan, plan_path, args.agent, False, findings, imported)
        emit(data, args.json)
        return exit_code(findings)
    finally:
        if locked:
            release_import_lock(brain, args.agent)


def cmd_write_wiki_proposals(args: argparse.Namespace) -> int:
    """Handle the `write-wiki-proposals` subcommand."""
    plan_path = Path(args.plan).expanduser()
    dry_run = not args.yes
    if not AGENT_ID_RE.match(args.agent):
        findings = [Finding("agent-id-missing", "block", "--as", "valid --as <agent-id> is required")]
        emit(proposal_result(None, plan_path, args.agent, dry_run, findings), args.json)
        return 1
    plan, findings, rc = load_plan(plan_path)
    if plan is None:
        emit(proposal_result(None, plan_path, args.agent, dry_run, findings), args.json)
        return rc
    findings.extend(proposal_gate_findings(plan, plan_path, args))
    brain = brain_path(str(plan.get("brain") or ""))

    if dry_run:
        data = proposal_result(plan, plan_path, args.agent, True, findings)
        emit(data, args.json)
        return exit_code(findings)

    try:
        node_id(brain)
    except ValueError as exc:
        findings.append(Finding(
            "federation-node-invalid", "block", FEDERATION_CONFIG_FILE,
            str(exc),
            "fix the node identity (or $BRAIN_NODE_ID) to a charset-safe value",
        ))
        data = proposal_result(plan, plan_path, args.agent, False, findings, None, [])
        emit(data, args.json)
        return exit_code(findings)

    proposal_dir: Path | None = None
    written: list[str] = []
    if not has_block(findings):
        proposal_dir, written, write_findings = write_proposal_artifacts(
            brain, plan_path, plan, args.agent
        )
        findings.extend(write_findings)
    data = proposal_result(plan, plan_path, args.agent, False, findings, proposal_dir, written)
    emit(data, args.json)
    return exit_code(findings)
