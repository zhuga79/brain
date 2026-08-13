"""Панели проектов: вкладки, содержимое папки-workspace и пустое состояние."""

from __future__ import annotations

from typing import Any

from .parts import (
    _client_for_role,
    _client_select,
    _fill_button,
    _launch_attrs,
    _mode_select,
    _proposal_for,
    _render_filter_row,
    _render_manual_launch,
    _short_path,
    _task_card,
    _task_group,
    _ws_basename,
)
from .tasks import _queue_group_cards
from .utils import h


def _render_workspaces(workspaces: dict[str, Any]) -> str:
    summary = workspaces.get("summary") or {}
    items = workspaces.get("items") or []
    roots = ", ".join(str(root) for root in workspaces.get("roots") or [])
    if not workspaces.get("configured"):
        rows = (
            "<tr><td colspan='3'><em>"
            f"{h(workspaces.get('error') or 'Workspace roots are not configured.')}"
            "</em></td></tr>"
        )
    elif not items:
        rows = "<tr><td colspan='3'><em>No workspaces found in configured roots</em></td></tr>"
    else:
        rows = ""
        for item in items:
            latest = item.get("latest_log") or {}
            rows += (
                f"<tr>"
                f"<td>{h(item.get('title') or '—')}<br><span class='mono small'>{h(item.get('path') or '')}</span></td>"
                f"<td>{h(item.get('open_tasks', 0))}</td>"
                f"<td>{h(latest.get('summary') or '—')}<br><span class='small'>{h(latest.get('timestamp') or '')}</span></td>"
                f"</tr>"
            )
    error = workspaces.get("error") or ""
    error_row = f"<p class='error'>{h(error)}</p>" if error and workspaces.get("configured") else ""
    return f"""
<section id="workspaces">
  <h2>Workspaces</h2>
  <p class="meta">Folder-native project folders. Configure scan roots with <code>BRAIN_DASHBOARD_WORKSPACE_ROOTS</code>.</p>
  <div class="summary-row">
    <div class="card"><strong>{h(summary.get('count', 0))}</strong><br>workspaces</div>
    <div class="card"><strong>{h(summary.get('open_tasks', 0))}</strong><br>open local tasks</div>
  </div>
  <p class="meta">Roots: <code>{h(roots or 'not configured')}</code></p>
  {error_row}
  <div class="ws-import">
    <h3>Импорт проекта из описания</h3>
    <p class="meta">Путь к JSON-файлу проекта или ссылка (http/https). Прочитаются имя, цель, задачи и роли.</p>
    <div class="filter-row">
      <label>Путь или ссылка <input id="ws-import-desc" type="text" placeholder="/путь/к/project.json или https://…" style="min-width:320px"></label>
      <label>Папка проекта <input id="ws-import-target" type="text" placeholder="/путь/к/папке проекта" style="min-width:320px"></label>
      <button type="button" class="button-primary" id="ws-import-btn" title="Прочитать и распарсить описание проекта">Импортировать</button>
    </div>
    <pre id="ws-import-out" class="kb-output" aria-live="polite"></pre>
  </div>
  <p class="meta">Задачи проектов и их запуск — на вкладке соответствующего проекта.</p>
  <table>
    <tr><th>Workspace</th><th>Open</th><th>Latest Log</th></tr>
    {rows}
  </table>
</section>"""


def _render_ws_panel(
    tid: str,
    it: dict[str, Any],
    providers: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    queue_tasks: list[dict[str, Any]] | None = None,
    queue_ctx: dict[str, Any] | None = None,
) -> str:
    """Full per-project view: metrics + task cards (grouped by state) + activity."""
    title = it.get("title") or _ws_basename(it.get("path", "")) or tid
    ws_path = it.get("path") or ""
    tasks = it.get("tasks") or []
    by_state: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        by_state.setdefault(t.get("state", "open"), []).append(t)
    counts = {st: len(v) for st, v in by_state.items()}
    metrics = "".join(
        f"<div class='card'><strong>{h(counts.get(st, 0))}</strong><br>{h(label)}</div>"
        for st, label in (("open", "open"), ("in-progress", "in progress"),
                          ("blocked", "blocked"), ("done", "done"))
    )

    def ws_card(task_id: str, task_title: str, prio: str, role: str, state: str) -> str:
        proposal = _proposal_for(proposals or [], task_id, ws_path)
        client = str(proposal.get("client") or "") or _client_for_role(providers, role)
        launch = _launch_attrs(task_id, role, client, ws_path, str(proposal.get("id") or ""))
        badges = (
            f"<span class='badge state-progress' title='Предложение автопилота: "
            f"{h(str(proposal.get('id') or ''))}'>автопилот</span>"
        ) if proposal else ""
        actions = (
            _mode_select(f"{ws_path}:{task_id}", "background")
            + _client_select(f"{ws_path}:{task_id}", client)
            + f"<button type='button' class='button-primary' data-kb-action='launch' {launch} title='Боевой запуск агента по задаче проекта'>▶ Запустить</button>"
            f"<button type='button' data-kb-action='dry-run' {launch} title='Пробный прогон: показать план запуска'>Проверить</button>"
            + _fill_button(task_id, role, client, ws_path)
        )
        return _task_card(
            task_id=task_id, title=task_title, priority=prio, actions=actions,
            state=state, role=role, badges=badges, meta=h(role or "no role"),
        )

    def state_group(state: str) -> str:
        rows = by_state.get(state, [])
        if not rows:
            return ""
        color = {"in-progress": "var(--cyan-fg)", "blocked": "var(--red-fg)",
                 "open": "var(--text)"}.get(state, "var(--text)")
        cards = "".join(
            ws_card(str(t.get("task_id", "")), str(t.get("title", "")),
                    str(t.get("priority", "")), str(t.get("role", "")), state)
            for t in rows
        )
        return (f"<div class='task-group'><h3 style=\"color:{color}\">{h(state)} "
                f"<span class='badge'>{len(rows)}</span></h3>"
                f"<div class='task-list'>{cards}</div></div>")

    next_task = it.get("next_task") or {}
    next_id = str(next_task.get("task_id") or "")
    next_row = ""
    if next_id:
        next_row = (
            "<div class='task-group'><h3>Следующая задача</h3><div class='task-list'>"
            + ws_card(next_id, str(next_task.get("title") or ""),
                      str(next_task.get("priority") or ""),
                      str(next_task.get("role") or ""),
                      str(next_task.get("state") or "open"))
            + "</div></div>"
        )

    board = state_group("in-progress") + state_group("open") + state_group("blocked")
    if not board:
        board = next_row or "<p class='meta'><em>нет задач в TASKS.md</em></p>"

    # задачи brain-очереди, привязанные к этому проекту (project: <папка>)
    queue_html = ""
    if queue_tasks and queue_ctx:
        ready, progress, blocked = _queue_group_cards(queue_tasks, **queue_ctx)
        queue_groups = (
            _task_group(f"{tid}-queue-ready", "Готовы к запуску", "var(--green-fg)", "".join(ready), len(ready))
            + _task_group(f"{tid}-queue-progress", "В работе", "var(--cyan-fg)", "".join(progress), len(progress))
        )
        if blocked:
            queue_groups += (
                f"<details class='task-fold'>"
                f"<summary>Заблокированы ({len(blocked)})</summary>"
                f"<div class='task-list'>{''.join(blocked)}</div>"
                f"</details>"
            )
        queue_html = (
            f"<div class='task-group'><h3>Очередь Brain "
            f"<span class='badge'>{len(queue_tasks)}</span></h3></div>"
            + queue_groups
        )

    # полноценная панель управления: фильтры + ручной запуск + свой вывод
    filter_row = _render_filter_row(list(queue_tasks or []) + list(tasks))
    manual_launch = _render_manual_launch(workspace_default=ws_path)
    output_box = "<pre class='task-action-output kb-output' aria-live='polite'></pre>"

    logs = it.get("log_entries") or []
    activity = ""
    if logs:
        log_rows = "".join(
            f"<tr><td class='mono small'>{h(e.get('timestamp', ''))}</td>"
            f"<td>{h(e.get('agent', ''))}</td><td>{h(e.get('summary', ''))}</td></tr>"
            for e in logs
        )
        activity = ("<h3>Activity</h3><table><tr><th>When</th><th>Agent</th>"
                    f"<th>Summary</th></tr>{log_rows}</table>")

    warns = it.get("warnings") or []
    warn_html = ("<ul class='ws-warn'>" + "".join(f"<li>{h(w)}</li>" for w in warns) + "</ul>") if warns else ""
    return (
        f'<div class="tab-panel" data-tab="{h(tid)}" role="tabpanel">\n'
        f'<section><h2>{h(title)}</h2>'
        f'<p class="meta">Path: <code title="{h(it.get("path", ""))}">{h(_short_path(it.get("path", "")))}</code></p>'
        f'<div class="summary-row">{metrics}</div>'
        f'{filter_row}{queue_html}{board}{manual_launch}{output_box}{activity}{warn_html}'
        f'</section></div>\n'
    )


def _render_ws_empty_panel() -> str:
    return (
        '<div class="tab-panel" data-tab="ws-empty" role="tabpanel">\n'
        '<section><h2>Проекты не найдены</h2>'
        '<p class="meta">Дашборд автоматически сканирует <code>$HOME</code> на файлы '
        '<code>BRAIN.md</code> — каждый такой проект становится отдельной вкладкой. '
        'Пока ни одного не найдено.</p>'
        '<p class="meta">Создай проект в любой папке:</p>'
        '<pre class="kb-output">brain-workspace init-template --out /путь/к/папке\n'
        '# отредактируй BRAIN.md (первый заголовок = ярлык вкладки), задачи — в TASKS.md</pre>'
        '<p class="meta">Сузить области сканирования: <code>BRAIN_DASHBOARD_WORKSPACE_ROOTS</code>. '
        'Глубина: <code>BRAIN_DASHBOARD_WS_MAX_DEPTH</code> (по умолчанию 6).</p>'
        '</section></div>\n'
    )


def _build_project_tabs(
    ws_items: list[dict[str, Any]],
    providers: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    queue_by_tab: dict[int, list[dict[str, Any]]] | None = None,
    queue_ctx: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (tabbar_html, panels_html): a tab per project (host + workspaces)."""
    btns = ['<button type="button" class="tab-btn active" data-tab-target="brain" role="tab">🧠 brain</button>']
    panels: list[str] = []
    for i, it in enumerate(ws_items):
        tid = f"ws-{i}"
        label = it.get("title") or _ws_basename(it.get("path", "")) or tid
        queue_tasks = (queue_by_tab or {}).get(i) or []
        badge = f" <span class='badge'>{len(queue_tasks)}</span>" if queue_tasks else ""
        btns.append(f'<button type="button" class="tab-btn" data-tab-target="{h(tid)}" role="tab">{h(label)}{badge}</button>')
        panels.append(_render_ws_panel(tid, it, providers, proposals, queue_tasks, queue_ctx))
    if not ws_items:
        btns.append('<button type="button" class="tab-btn tab-add" data-tab-target="ws-empty" role="tab">+ проект</button>')
        panels.append(_render_ws_empty_panel())
    tabbar = '<nav class="tabbar" role="tablist">' + "".join(btns) + "</nav>\n"
    return tabbar, "".join(panels)
