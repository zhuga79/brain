"""Мелкие элементы страницы: значки, карточка задачи, поля выбора, кнопки.

Здесь всё, что переиспользуют несколько областей сразу: карточка задачи нужна и
в очереди Brain, и в панели проекта, поля выбора клиента и режима — везде, где
можно запустить агента. Отдельный модуль, потому что иначе эти элементы
пришлось бы дублировать или тянуть импортом крест-накрест.
"""

from __future__ import annotations

from typing import Any

from brain_launch_queue import ALLOWED_CLIENTS

from .utils import h, _option_list


def _provider_label(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    effort = f" {item.get('effort')}" if item.get("effort") else ""
    return f"{item.get('provider', '')}/{item.get('model', '')}{effort}".strip("/")


def _provider_client(item: dict[str, Any] | None) -> str:
    if not item:
        return "codex"
    provider = str(item.get("provider") or "").strip()
    if provider in {"codex", "claude", "gemini", "ollama", "opencode", "kilocode"}:
        return provider
    command = str(item.get("command") or "").strip().split()
    if command and command[0] in {"codex", "claude", "gemini", "ollama", "opencode", "kilocode"}:
        return command[0]
    return "codex"


def _client_for_role(providers: dict[str, Any] | None, role: str) -> str:
    roles = (providers or {}).get("roles", {}) if isinstance(providers, dict) else {}
    preferred = (roles.get(role) or {}).get("preferred") if isinstance(roles, dict) else None
    return _provider_client(preferred) or "codex"


def _task_blockers(task: dict[str, Any], active_ids: set[str], done_ids: set[str]) -> list[str]:
    blockers: list[str] = []
    if task.get("state") == "!":
        blockers.append("state blocked")
    for dep in task.get("depends_on") or []:
        dep_id = str(dep)
        if dep_id in done_ids:
            continue
        if dep_id in active_ids:
            blockers.append(f"depends: {dep_id}")
        else:
            blockers.append(f"missing: {dep_id}")
    return blockers


def _task_sort_key(item: tuple[dict[str, Any], list[str]]) -> tuple[int, str, str]:
    task, blockers = item
    return (1 if blockers else 0, str(task.get("priority") or ""), str(task.get("id") or ""))


def _task_project(task: dict[str, Any]) -> str:
    """Имя проекта задачи: поле project: из разобранной структуры.

    Разбор живёт в brain_task_parser.parse_block; здесь сырые строки блока не
    перечитываются — дашборд берёт проект наравне с остальными полями.
    """
    return str(task.get("project") or "").strip()


def _task_card(
    *,
    task_id: str,
    title: str,
    priority: str,
    actions: str,
    state: str = "",
    role: str = "",
    mode: str = "",
    provider: str = "",
    client: str = "",
    badges: str = "",
    meta: str = "",
    card_cls: str = "",
    filterable: bool = True,
) -> str:
    text_blob = " ".join((task_id, title, priority, role, mode, client)).lower()
    prio_cls = f"prio-{priority}" if priority else ""
    meta_html = f"<div class='task-card-meta'>{meta}</div>" if meta else ""
    filter_attr = " data-filter-row='task'" if filterable else ""
    return (
        f"<div class='task-card {h(prio_cls)} {h(card_cls)}'{filter_attr}"
        f" data-state='{h(state)}' data-priority='{h(priority)}' data-role='{h(role)}'"
        f" data-mode='{h(mode)}' data-provider='{h(provider)}' data-client='{h(client)}'"
        f" data-text='{h(text_blob)}'>"
        f"<div class='task-card-main'>"
        f"<div class='task-card-title'>"
        + (f"<span class='badge badge-prio'>{h(priority)}</span>" if priority else "")
        + f" <span class='mono small'>{h(task_id)}</span> <strong>{h(title)}</strong> {badges}</div>"
        f"{meta_html}"
        f"</div>"
        f"<div class='task-card-actions'>{actions}</div>"
        f"</div>"
    )


def _task_group(gid: str, label: str, color: str, cards: str, count: int) -> str:
    if not cards:
        return ""
    return (
        f"<div class='task-group' id='{h(gid)}'>"
        f"<h3 style='color:{color}'>{h(label)} <span class='badge'>{count}</span></h3>"
        f"<div class='task-list'>{cards}</div>"
        f"</div>"
    )


def _ws_basename(path: str) -> str:
    return path.rstrip("/").split("/")[-1] if path else ""


def _short_path(path: str, keep: int = 2) -> str:
    """Last `keep` path segments with a leading ellipsis; full path stays in title."""
    parts = [p for p in path.rstrip("/").split("/") if p]
    if len(parts) <= keep:
        return path
    return "…/" + "/".join(parts[-keep:])


LAUNCH_MODES = (("interactive", "интерактив"), ("background", "фон"))


def _client_select(key: str, default_client: str) -> str:
    opts = "".join(
        f"<option value='{h(c)}'{' selected' if c == default_client else ''}>{h(c)}</option>"
        for c in ALLOWED_CLIENTS
    )
    return (
        f"<select class='task-client' data-client-key='{h(key)}'"
        f" title='CLI для запуска'>{opts}</select>"
    )


def _mode_select(key: str, default_mode: str) -> str:
    opts = "".join(
        f"<option value='{h(value)}'{' selected' if value == default_mode else ''}>{h(label)}</option>"
        for value, label in LAUNCH_MODES
    )
    return (
        f"<select class='task-mode' data-mode-key='{h(key)}'"
        f" title='Режим запуска: интерактивный терминал или фоновый'>{opts}</select>"
    )


def _default_mode(surface: str) -> str:
    return "interactive" if surface == "interactive" else "background"


def _launch_attrs(task_id: str, role: str, client: str, workspace: str, proposal_id: str = "") -> str:
    attrs = (
        f"data-kb-task='{h(task_id)}' data-kb-role='{h(role)}'"
        f" data-kb-client='{h(client)}' data-kb-workspace='{h(workspace)}'"
    )
    if proposal_id:
        attrs += f" data-kb-proposal='{h(proposal_id)}'"
    return attrs


def _fill_button(task_id: str, role: str, client: str, workspace: str) -> str:
    return (
        f"<button type='button'"
        f" data-launch-fill-task='{h(task_id)}'"
        f" data-launch-fill-role='{h(role)}'"
        f" data-launch-fill-client='{h(client)}'"
        f" data-launch-fill-workspace='{h(workspace)}'"
        f" title='Заполнить форму ручного запуска (модель, effort)'>Подготовить</button>"
    )


def _pending_proposals(queue: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending autopilot proposals from the launch queue."""
    return [
        p for p in (queue.get("proposals") or [])
        if isinstance(p, dict) and str(p.get("status") or "pending") == "pending"
    ]


def _proposal_for(proposals: list[dict[str, Any]], task_id: str, workspace: str) -> dict[str, Any]:
    """Match a pending proposal to a task within the given workspace scope."""
    for p in proposals:
        if str(p.get("task") or "") != task_id:
            continue
        p_ws = str(p.get("workspace") or "")
        if p_ws == workspace or (not p_ws and not workspace):
            return p
    return {}


def _render_filter_row(tasks: list[dict[str, Any]], *, with_ids: bool = False) -> str:
    """Строка фильтров панели задач. Скоуп — ближайшая секция (см. assets.FILTER_SCRIPT).
    with_ids — легаси-идентификаторы для вкладки brain."""
    container_id = ' id="task-filters"' if with_ids else ""
    return f"""
  <div{container_id} class="task-filters filter-row">
    <label>Text <input class="task-filter-text" type="search" placeholder="task, title, role"></label>
    <label>Priority <select class="task-filter-priority">{_option_list([t.get('priority', '') for t in tasks], 'all')}</select></label>
    <label>Role <select class="task-filter-role">{_option_list([t.get('role', '') for t in tasks], 'all')}</select></label>
    <label>Mode <select class="task-filter-mode">{_option_list([t.get('mode', '') for t in tasks], 'all')}</select></label>
    <label>Client <select class="task-filter-client">{_option_list([t.get('client', '') for t in tasks], 'all')}</select></label>
    <button type="button" class="task-filter-reset" title="Сбросить все фильтры задач">Сбросить</button>
    <span class="meta"><span class="task-filter-count">{h(len(tasks))}</span> shown</span>
  </div>"""


def _render_manual_launch(*, workspace_default: str = "", with_ids: bool = False) -> str:
    """Свёртка «Ручной запуск» — по одной на каждой вкладке; поля скоупятся классами."""
    def ident(name: str) -> str:
        return f' id="{name}"' if with_ids else ""
    client_options = "".join(f"<option value='{h(c)}'>{h(c)}</option>" for c in ALLOWED_CLIENTS)
    return f"""
<details class="manual-launch"><summary>Ручной запуск (по параметрам)</summary>
<section{' id="launch-panel"' if with_ids else ''} class="launch-panel">
  <h3>Параметры ручного запуска</h3>
  <div class="filter-row">
    <label>Workspace <input{ident("launch-workspace")} class="launch-workspace" type="text" placeholder="/path/to/project" value="{h(workspace_default)}"></label>
    <label>Task <input{ident("launch-task")} class="launch-task" type="text" placeholder="task-id"></label>
    <label>Role <input{ident("launch-role")} class="launch-role" type="text" placeholder="lawyer"></label>
    <label>CLI
      <select{ident("launch-client")} class="launch-client">{client_options}</select>
    </label>
    <label>Режим
      <select{ident("launch-mode")} class="launch-mode" title="Интерактивный терминал или фоновый запуск">{"".join(f"<option value='{h(v)}'>{h(lbl)}</option>" for v, lbl in LAUNCH_MODES)}</select>
    </label>
    <label>Model
      <select{ident("launch-model")} class="launch-model" title="Модели подгружаются из выбранного CLI при «Подготовить» или смене CLI"><option value="">авто (по роли)</option></select>
    </label>
    <label>Effort <input{ident("launch-effort")} class="launch-effort" type="text" placeholder="medium"></label>
    <label><input{ident("launch-dry-run")} class="launch-dry-run" type="checkbox"> dry run</label>
    <button type="button"{ident("launch-btn")} class="launch-btn" title="Запустить агента вручную с указанными параметрами">Запустить</button>
  </div>
  <pre{ident("launch-output")} class="launch-output kb-output" aria-live="polite"></pre>
</section>
</details>"""
