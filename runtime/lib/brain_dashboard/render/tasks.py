"""Области страницы, посвящённые задачам: дерево, очередь, операции."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .labels import STATE_CLASS, STATE_LABELS
from .parts import (
    _client_for_role,
    _client_select,
    _default_mode,
    _fill_button,
    _launch_attrs,
    _mode_select,
    _pending_proposals,
    _task_project,
    _proposal_for,
    _provider_label,
    _render_filter_row,
    _render_manual_launch,
    _task_blockers,
    _task_card,
    _task_group,
    _task_sort_key,
    _ws_basename,
)
from .utils import h, _provider_badge, _provider_for_role, _surface_badge


def _render_task_tree_candidates(
    active_tasks: list[dict[str, Any]],
    done_tasks: list[dict[str, Any]],
    providers: dict[str, Any],
    all_active: list[dict[str, Any]] | None = None,
) -> str:
    active_ids = {str(t.get("id") or "") for t in (all_active if all_active is not None else active_tasks)}
    done_ids = {str(t.get("id") or "") for t in done_tasks}
    role_providers = providers.get("roles", {}) if isinstance(providers, dict) else {}

    task_pairs = [(task, _task_blockers(task, active_ids, done_ids)) for task in active_tasks]
    candidate_rows = ""
    for task, blockers in sorted(task_pairs, key=_task_sort_key):
        role = str(task.get("role") or "")
        provider_info = role_providers.get(role, {}) if isinstance(role_providers, dict) else {}
        preferred = provider_info.get("preferred") or {}
        fallback = provider_info.get("fallback") or []
        unavailable = provider_info.get("unavailable") or []
        fallback_labels = ", ".join(_provider_label(item) for item in fallback[:2] if item) or "—"
        unavailable_labels = ", ".join(_provider_label(item) for item in unavailable[:2] if item)
        if unavailable_labels:
            fallback_labels = f"{fallback_labels}; unavailable: {unavailable_labels}"
        blocker_text = f"blocked: {'; '.join(blockers)}" if blockers else "ready"
        ready_cls = "state-done" if not blockers else "state-blocked"
        ready_label = "ready" if not blockers else "blocked"
        candidate_rows += (
            f"<tr>"
            f"<td><span class='badge {h(ready_cls)}'>{h(ready_label)}</span></td>"
            f"<td><span class='mono'>{h(task.get('id') or '')}</span><br><span class='small'>{h(task.get('title') or '')}</span></td>"
            f"<td>{h(role or '—')}</td>"
            f"<td>{_provider_badge(preferred, 'state-done') if preferred else '<em>none</em>'}</td>"
            f"<td>{h(fallback_labels)}</td>"
            f"<td>{h(blocker_text)}</td>"
            f"</tr>"
        )
    if not candidate_rows:
        candidate_rows = "<tr><td colspan='6'><em>Нет готовых к запуску</em></td></tr>"

    by_parent: dict[str, list[dict[str, Any]]] = {}
    task_by_id = {str(t.get("id") or ""): t for t in active_tasks}
    for task in active_tasks:
        parent = str(task.get("parent") or "")
        if not parent and (task.get("depends_on") or []):
            first_dep = str((task.get("depends_on") or [""])[0])
            if first_dep in task_by_id:
                parent = first_dep
        by_parent.setdefault(parent, []).append(task)
    for children in by_parent.values():
        children.sort(key=lambda t: (str(t.get("priority") or ""), str(t.get("id") or "")))

    tree_rows = ""
    seen: set[str] = set()

    def add_tree_rows(parent: str, depth: int) -> None:
        nonlocal tree_rows
        for task in by_parent.get(parent, []):
            task_id = str(task.get("id") or "")
            if task_id in seen:
                continue
            seen.add(task_id)
            role = str(task.get("role") or "")
            provider_info = role_providers.get(role, {}) if isinstance(role_providers, dict) else {}
            preferred = provider_info.get("preferred") or {}
            blockers = _task_blockers(task, active_ids, done_ids)
            deps = ", ".join(str(dep) for dep in (task.get("depends_on") or [])) or "—"
            parent_label = task.get("parent") or "—"
            state_label = STATE_LABELS.get(task.get("state"), task.get("state") or "")
            state_cls = STATE_CLASS.get(task.get("state"), "")
            connector = "└─ " if depth else ""
            status_text = f"blocked: {'; '.join(blockers)}" if blockers else "ready"
            tree_rows += (
                f"<tr>"
                f"<td><span class='badge {h(state_cls)}'>{h(state_label)}</span></td>"
                f"<td>{h(task.get('priority') or '')}</td>"
                f"<td style='padding-left:{h(8 + depth * 20)}px'><span class='mono'>{h(connector + task_id)}</span><br><span class='small'>{h(task.get('title') or '')}</span></td>"
                f"<td>{h(role or '—')}</td>"
                f"<td>{_provider_badge(preferred, 'state-done') if preferred else '<em>none</em>'}</td>"
                f"<td class='mono small'>{h(parent_label)}</td>"
                f"<td class='mono small'>{h(deps)}</td>"
                f"<td>{h(status_text)}</td>"
                f"</tr>"
            )
            add_tree_rows(task_id, depth + 1)

    add_tree_rows("", 0)
    for task in active_tasks:
        if str(task.get("id") or "") not in seen:
            by_parent.setdefault("__orphans__", []).append(task)
    add_tree_rows("__orphans__", 0)

    if not tree_rows:
        recent_done = done_tasks[:8]
        for task in recent_done:
            role = str(task.get("role") or "")
            provider_info = role_providers.get(role, {}) if isinstance(role_providers, dict) else {}
            preferred = provider_info.get("preferred") or {}
            tree_rows += (
                f"<tr>"
                f"<td><span class='badge state-done'>done</span></td>"
                f"<td>{h(task.get('priority') or '')}</td>"
                f"<td><span class='mono'>{h(task.get('id') or '')}</span><br><span class='small'>{h(task.get('title') or '')}</span></td>"
                f"<td>{h(role or '—')}</td>"
                f"<td>{_provider_badge(preferred, 'state-done') if preferred else '<em>none</em>'}</td>"
                f"<td class='mono small'>{h(task.get('parent') or '—')}</td>"
                f"<td class='mono small'>{h(', '.join(str(dep) for dep in (task.get('depends_on') or [])) or '—')}</td>"
                f"<td>recent done</td>"
                f"</tr>"
            )
        if not tree_rows:
            tree_rows = "<tr><td colspan='8'><em>No task tree yet</em></td></tr>"

    return f"""
<section id="task-tree">
  <h2>Task Tree & Candidates</h2>
  <p class="meta">Over-project Brain view: tasks come from this Brain queue, while Launch can send the selected role/CLI into any project workspace.</p>
  <h3>Runnable Candidates</h3>
  <table id="candidate-table">
    <tr><th>Ready</th><th>Task</th><th>Role</th><th>Primary CLI/model</th><th>Fallback</th><th>Blockers</th></tr>
    {candidate_rows}
  </table>
  <h3>Task Tree</h3>
  <table>
    <tr><th>State</th><th>Prio</th><th>Task</th><th>Role</th><th>Candidate</th><th>Parent</th><th>Depends</th><th>Status</th></tr>
    {tree_rows}
  </table>
</section>"""


def _match_project_tab(project: str, ws_items: list[dict[str, Any]]) -> int | None:
    """Индекс вкладки проекта по имени проектной папки (или заголовку)."""
    key = project.strip().lower()
    if not key:
        return None
    for i, it in enumerate(ws_items):
        base = _ws_basename(str(it.get("path") or "")).lower()
        title = str(it.get("title") or "").strip().lower()
        if key == base or key == title:
            return i
    return None


def _queue_group_cards(
    display_tasks: list[dict[str, Any]],
    *,
    active_ids: set[str],
    done_ids: set[str],
    providers: dict[str, Any],
    proposals: list[dict[str, Any]],
    locks_by_task: dict[str, dict[str, Any]],
    ws: str,
    show_project_badge: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """Карточки brain-очереди по группам: (готовы, в работе, заблокированы)."""

    def sort_key(t: dict[str, Any]) -> tuple[str, str]:
        return (str(t.get("priority") or "P9"), str(t.get("id") or ""))

    def base_badges(t: dict[str, Any], proposal: dict[str, Any]) -> str:
        surface = t.get("surface") or "headless"
        badges = _surface_badge(surface)
        if surface == "interactive":
            badges += "<span class='window-affordance' title='Requires visible window'>↗ window</span>"
        if proposal:
            badges += (
                f"<span class='badge state-progress' title='Предложение автопилота: "
                f"{h(str(proposal.get('id') or ''))}'>автопилот</span>"
            )
        lock = locks_by_task.get(str(t.get("id") or ""))
        if lock:
            lock_cls = "state-blocked" if lock.get("stale") else "state-progress"
            badges += (
                f"<span class='badge {lock_cls}' title='Лок агента"
                f"{' (протух)' if lock.get('stale') else ''}'>🔒 {h(str(lock.get('owner') or '?'))}</span>"
            )
        if show_project_badge:
            project = _task_project(t)
            if project:
                badges += (
                    f"<span class='badge' title='Проект без вкладки: создайте BRAIN.md "
                    f"в папке проекта'>📁 {h(project)}</span>"
                )
        client_name = t.get("client") or ""
        if client_name:
            badges += (
                f"<span class='badge state-progress' "
                f"title='Заказчик — единица биллинга (часы и отчёты)'>👤 {h(client_name)}</span>"
            )
        return badges

    ready_cards: list[str] = []
    progress_cards: list[str] = []
    blocked_cards: list[str] = []
    for t in sorted(display_tasks, key=sort_key):
        tid = str(t.get("id") or "")
        role = str(t.get("role") or "")
        mode = str(t.get("mode") or "")
        prio = str(t.get("priority") or "")
        title = str(t.get("title") or tid)
        state = str(t.get("state") or " ")
        blockers = _task_blockers(t, active_ids, done_ids)
        provider = _provider_for_role(providers, role)
        proposal = _proposal_for(proposals, tid, "") or _proposal_for(proposals, tid, ws)
        client = str(proposal.get("client") or "") or _client_for_role(providers, role)
        launch = _launch_attrs(tid, role, client, ws, str(proposal.get("id") or ""))
        meta = h(role or "no role") + (f" · {h(mode)}" if mode else "")
        if provider:
            meta += f" · {h(provider)}"

        if state == "~":
            actions = (
                f"<button type='button' data-kb-action='status' {launch} title='Показать последние события по задаче'>Статус</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='release' title='Снять лок и вернуть в очередь'>Пауза</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='complete' title='Отметить выполненной и перенести в историю'>Завершить</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='block' title='Заблокировать с причиной'>Отменить</button>"
            )
            progress_cards.append(_task_card(
                task_id=tid, title=title, priority=prio, actions=actions,
                state=state, role=role, mode=mode, provider=provider,
                client=str(t.get("client") or ""),
                badges=base_badges(t, proposal), meta=meta,
            ))
        elif blockers:
            meta += f" · <span class='error'>блокеры: {h('; '.join(blockers))}</span>"
            actions = (
                f"<button type='button' data-kb-action='status' {launch} title='Показать последние события по задаче'>Статус</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='release' title='Вернуть задачу в очередь'>Вернуть</button>"
                + _fill_button(tid, role, client, ws)
            )
            blocked_cards.append(_task_card(
                task_id=tid, title=title, priority=prio, actions=actions,
                state=state, role=role, mode=mode, provider=provider,
                client=str(t.get("client") or ""),
                badges=base_badges(t, proposal), meta=meta,
            ))
        else:
            actions = (
                _mode_select(tid, _default_mode(str(t.get("surface") or "headless")))
                + _client_select(tid, client)
                + f"<button type='button' class='button-primary' data-kb-action='launch' {launch} title='Боевой запуск агента по задаче'>▶ Запустить</button>"
                f"<button type='button' data-kb-action='dry-run' {launch} title='Пробный прогон: показать план запуска'>Проверить</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='take' title='Взять в работу (поставить лок)'>Взять</button>"
                f"<button type='button' data-task='{h(tid)}' data-action='block' title='Заблокировать с причиной'>Заблокировать</button>"
                + _fill_button(tid, role, client, ws)
            )
            ready_cards.append(_task_card(
                task_id=tid, title=title, priority=prio, actions=actions,
                state=state, role=role, mode=mode, provider=provider,
                client=str(t.get("client") or ""),
                badges=base_badges(t, proposal), meta=meta,
            ))
    return ready_cards, progress_cards, blocked_cards


def _render_task_ops(
    active_tasks: list[dict[str, Any]],
    done_tasks: list[dict[str, Any]],
    providers: dict[str, Any],
    status: dict[str, Any],
    brain: Path,
    display_tasks: list[dict[str, Any]] | None = None,
) -> str:
    """Единый блок управления задачами: готовые к запуску / в работе /
    заблокированные, автопилот и циклы — внутри карточек, один вывод.
    display_tasks — задачи для показа (без привязанных к проектам);
    блокеры считаются по полной очереди active_tasks."""
    if display_tasks is None:
        display_tasks = active_tasks
    active_ids = {str(t.get("id") or "") for t in active_tasks}
    done_ids = {str(t.get("id") or "") for t in done_tasks}
    proposals = _pending_proposals(status.get("queue_autopilot", {}))
    locks_by_task = {
        str(lock.get("task_id") or ""): lock
        for lock in (status.get("locks", {}).get("items") or [])
    }
    ws = str(brain)

    ready_cards, progress_cards, blocked_cards = _queue_group_cards(
        display_tasks,
        active_ids=active_ids, done_ids=done_ids, providers=providers,
        proposals=proposals, locks_by_task=locks_by_task, ws=ws,
        show_project_badge=True,
    )

    groups = (
        _task_group("task-ops-ready", "Готовы к запуску", "var(--green-fg)", "".join(ready_cards), len(ready_cards))
        + _task_group("task-ops-progress", "В работе", "var(--cyan-fg)", "".join(progress_cards), len(progress_cards))
    )
    if blocked_cards:
        groups += (
            f"<details class='task-fold' id='task-ops-blocked'>"
            f"<summary>Заблокированы ({len(blocked_cards)})</summary>"
            f"<div class='task-list'>{''.join(blocked_cards)}</div>"
            f"</details>"
        )
    if not groups:
        groups = "<p><em>No active tasks.</em></p>"

    # циклические задачи (systemd-таймеры brain-*)
    timers = ((status.get("scheduled") or {}).get("systemd_timers") or {}).get("items") or []
    brain_timers = [it for it in timers if str(it.get("unit", "")).startswith("brain-")]
    cyc_cards = ""
    for it in brain_timers:
        unit = str(it.get("unit", ""))
        name = unit.replace(".timer", "").replace("brain-", "")
        nxt = str(it.get("next", "") or it.get("activates", "") or "—")
        actions = (
            f"<button type='button' data-kb-action='cycle-run' data-kb-unit='{h(unit)}' title='Запустить этот цикл прямо сейчас'>Запустить сейчас</button>"
            f"<button type='button' data-kb-action='cycle-status' data-kb-unit='{h(unit)}' data-kb-next='{h(nxt)}' title='Показать расписание цикла'>Статус</button>"
        )
        cyc_cards += (
            f"<div class='task-card prio-cyclic'>"
            f"<div class='task-card-main'>"
            f"<div class='task-card-title'><strong>{h(name)}</strong></div>"
            f"<div class='task-card-meta'>следующий запуск: <span class='mono'>{h(nxt)}</span></div>"
            f"</div>"
            f"<div class='task-card-actions'>{actions}</div>"
            f"</div>"
        )
    cycles_fold = (
        f"<details class='task-fold' id='task-ops-cycles'>"
        f"<summary>Циклические ({len(brain_timers)})</summary>"
        f"<div class='task-list'>{cyc_cards}</div>"
        f"</details>"
    ) if cyc_cards else ""

    filter_row = _render_filter_row(display_tasks, with_ids=True)

    summary = status["tasks"]["summary"]
    return f"""
<section id="task-operations" class="primary-surface">
  <h2>Задачи
    <span class="badge state-open"><span id="sse-tasks-active">{h(summary['active_count'])}</span> active</span>
    <span class="badge state-done"><span id="sse-tasks-done">{h(summary['done_count'])}</span> done</span>
  </h2>
  {filter_row}
  {groups}
  {cycles_fold}
  {_render_manual_launch(workspace_default=ws, with_ids=True)}
  <pre id="task-action-output" class="task-action-output kb-output" aria-live="polite"></pre>
</section>"""


def _render_command_center(
    active_tasks: list[dict[str, Any]],
    done_tasks: list[dict[str, Any]],
    status: dict[str, Any],
) -> str:
    active_ids = {str(t.get("id") or "") for t in active_tasks}
    done_ids = {str(t.get("id") or "") for t in done_tasks}
    runnable = sum(1 for task in active_tasks if not _task_blockers(task, active_ids, done_ids))
    blocked = max(0, len(active_tasks) - runnable)
    locks = status.get("locks", {})
    stale_locks = int(locks.get("stale_count", 0) or 0)
    scheduled_total = sum(int(v or 0) for v in (status.get("scheduled", {}).get("summary") or {}).values())
    index_health = str((status.get("index") or {}).get("health", "unknown"))
    handoff = status.get("handoff") or {}
    handoff_state = handoff.get("reason") if handoff.get("exists") else "none"

    def tone(value: str) -> str:
        return value if value in {"good", "warn", "bad"} else ""

    queue_tone = "good" if runnable else ("warn" if active_tasks else "")
    blocked_tone = "bad" if blocked or stale_locks else "good"
    index_tone = "good" if index_health == "ok" else "bad"
    handoff_tone = "warn" if handoff_state != "none" else "good"
    scheduled_tone = "warn" if scheduled_total else ""

    return f"""
<section id="command-center">
  <h2>Сейчас</h2>
  <div class="command-grid">
    <div class="metric-card {h(tone(queue_tone))}"><strong>{h(runnable)}</strong><span>Runnable now</span></div>
    <div class="metric-card {h(tone(blocked_tone))}"><strong>{h(blocked)}</strong><span>Blocked candidates</span></div>
    <div class="metric-card {h(tone(scheduled_tone))}"><strong>{h(scheduled_total)}</strong><span>Scheduled outside queue</span></div>
    <div class="metric-card {h(tone(index_tone))}"><strong>{h(index_health)}</strong><span>Index health</span></div>
    <div class="metric-card {h(tone(handoff_tone))}"><strong>{h(handoff_state)}</strong><span>Handoff state</span></div>
    <div class="metric-card"><strong>{h(stale_locks)}</strong><span>Stale locks</span></div>
  </div>
  <div class="command-actions">
    <a href="#task-operations">Queue</a>
    <a href="#task-tree">Candidates</a>
    <a href="#launch-panel">Launch</a>
    <a href="#scheduled-work">Scheduled</a>
    <a href="#workspaces">Workspaces</a>
    <a href="#operator-console">Operator</a>
    <a href="#providers">Providers</a>
  </div>
</section>"""
