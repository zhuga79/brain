"""brain-dashboard HTML orchestrator — assembles the full dashboard page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import assets, diagnostics
from .operator import (
    build_handoff_limits,
    build_operator_console,
    build_search,
)
from .parts import _pending_proposals
from .scheduled import _render_scheduled_work
from .tasks import (
    _render_command_center,
    _render_task_ops,
    _render_task_tree_candidates,
)
from .workspaces import _build_project_tabs, _render_workspaces
from .utils import h, _provider_for_role
from .sections import (
    build_wiki_pages_section,
    build_delta_section,
    build_handoff_journal_section,
    build_provider_cards_section,
    build_activity_section,
)


def build_html(
    status: dict[str, Any],
    brain: Path,
    generated_at: str,
    live_refresh: bool = False,
    delta: dict[str, Any] | None = None,
    task_filter: str = "",
    audit_entries: list[dict[str, str]] | None = None,
) -> str:
    summary = status["tasks"]["summary"]
    active_tasks = status["tasks"]["active"]
    done_tasks = status["tasks"].get("done", [])
    locks = status["locks"]["items"]
    councils = status["council"]["items"]
    index = status["index"]
    providers = status.get("providers", {})
    tokens = status.get("tokens", {})
    handoff = status.get("handoff", {})
    operator = status.get("operator", {})
    obsidian_views = status.get("obsidian_views", {})
    audit_entries = audit_entries or []

    provider_by_role = {
        role: _provider_for_role(providers, role)
        for role in set((t.get("role") or "") for t in active_tasks + done_tasks)
    }

    # аналитика по задачам (диагностика; операции — в #task-operations)
    task_stats_section = diagnostics.build_task_stats(active_tasks, done_tasks, provider_by_role, summary)

    # locks section
    locks_section = diagnostics.build_locks(locks, status)

    # council section
    council_section = diagnostics.build_council(councils, status)

    # index section
    index_section = diagnostics.build_index(index)

    # knowledge graph section
    graph_section = diagnostics.build_graph(status)

    # release gates preview section
    release_blockers = diagnostics.release_blockers_of(index, status, summary)
    release_label = diagnostics.release_label_of(release_blockers)
    release_section = diagnostics.build_release_gates(index, status, summary)

    operator_section = build_operator_console(brain, handoff, operator, providers, release_blockers, release_label, tokens)

    handoff_section = build_handoff_limits(brain, handoff)

    # obsidian-views section
    obsidian_section = diagnostics.build_obsidian_views(obsidian_views)

    provider_section = build_provider_cards_section(providers)
    scheduled_section = _render_scheduled_work(status.get("scheduled", {}))

    # token economy section
    token_section = diagnostics.build_token_economy(tokens)

    # learning stats section
    learning_section = diagnostics.build_learning(status)

    # audit log section
    audit_section = diagnostics.build_audit_log(audit_entries, task_filter)

    activity_section = build_activity_section(status, provider_by_role)
    handoff_journal_section = build_handoff_journal_section(status.get("handoff_journal", []))

    search_section = build_search()

    wiki_pages_section = build_wiki_pages_section(status.get("wiki", {}))

    command_center = _render_command_center(active_tasks, done_tasks, status)
    workspace_section = _render_workspaces(status.get("workspaces", {}))
    _ws_items = (status.get("workspaces") or {}).get("items") or []
    _proposals = _pending_proposals(status.get("queue_autopilot", {}))

    task_ops_section = _render_task_ops(
        active_tasks, done_tasks, providers, status, brain,
    )
    tabbar, ws_panels = _build_project_tabs(_ws_items, providers, _proposals)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="generated-at" content="{h(generated_at)}">\n'
        f'<meta name="state-sig" content="{h(status.get("signature", ""))}">\n'
        + assets.FILTER_SCRIPT
        + (assets.SSE_SCRIPT if live_refresh else "")
        + assets.SEARCH_SCRIPT
        + assets.WORKSPACE_IMPORT_SCRIPT
        + assets.VIEW_SCRIPT
        + (assets.STATUS_POLL_SCRIPT if live_refresh else "")
        + "<title>Brain Dashboard</title>\n"
        f"<style>\n{assets.CSS}\n{assets.TAB_CSS}\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="topbar">\n'
        '<div class="topbar-row">\n'
        "<div><h1>Brain Visual Shell</h1>\n"
        f'<p class="meta">Path: <code>{h(str(brain))}</code>'
        f" &nbsp;|&nbsp; Generated: <span id='sse-meta'>{h(generated_at)}</span></p></div>\n"
        '<div class="toolbar">'
        '<button type="button" data-view-toggle="compact" aria-pressed="false" title="Компактный вид: уменьшить отступы и размер таблиц">Компактно</button>'
        '<button type="button" data-view-toggle="diagnostics" aria-pressed="true" title="Показать/скрыть диагностические данные">Диагностика</button>'
        "</div>\n"
        "</div>\n"
        '<nav class="quick-nav">'
        '<a href="#command-center">Сейчас</a>'
        '<a href="#task-operations">Задачи</a>'
        '<a href="#queue-autopilot">Запуск</a>'
        "</nav>\n"
        "</div>\n"
        f"{tabbar}"
        '<div class="tab-panel active" data-tab="brain" role="tabpanel">\n'
        f"{command_center}\n"
        f"{task_ops_section}\n"
        '<details class="secondary-group"><summary>Подробности и диагностика</summary>\n'
        f"{_render_task_tree_candidates(active_tasks, done_tasks, providers, all_active=active_tasks)}\n"
        f"{task_stats_section}\n"
        f"{activity_section}\n"
        f"{operator_section}\n"
        f"{scheduled_section}\n"
        f"{workspace_section}\n"
        f"{search_section}\n"
        f"{locks_section}\n"
        f"{council_section}\n"
        f"{index_section}\n"
        f"{graph_section}\n"
        f"{release_section}\n"
        f"{handoff_section}\n"
        f"{handoff_journal_section}\n"
        f"{obsidian_section}\n"
        f"{wiki_pages_section}\n"
        f"{provider_section}\n"
        f"{token_section}\n"
        f"{learning_section}\n"
        f"{audit_section}\n"
        '</details>\n'
        + (build_delta_section(delta) + "\n" if delta and delta.get("has_delta") else "")
        + "</div>\n"
        + ws_panels
        + assets.TAB_SCRIPT
        + assets.LAUNCH_SCRIPT
        + assets.TASK_OPS_SCRIPT
        + "</body>\n"
        "</html>\n"
    )
