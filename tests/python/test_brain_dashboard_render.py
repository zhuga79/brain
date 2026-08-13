import pytest
import json
from pathlib import Path

from brain_dashboard.render.utils import h, counter_table, _option_list, _provider_for_role, _group_counts, _provider_badge
from brain_dashboard.render.sections import (
    build_delta_section,
    build_handoff_journal_section,
    build_provider_cards_section,
    build_activity_section,
    build_wiki_pages_section
)
from brain_dashboard.render.html import build_html

def test_h():
    assert h("<script>") == "&lt;script&gt;"
    assert h(None) == "None"

def test_counter_table():
    c = {"a": 2, "b": 1}
    html = counter_table(c)
    assert "<td>a</td>" in html
    assert "<td>2</td>" in html
    assert counter_table({}) == "<em>—</em>"
    
def test_option_list():
    html = _option_list(["a", "b"], "all")
    assert "<option value=''>all</option>" in html
    assert "<option value='a'>a</option>" in html

def test_provider_for_role():
    providers = {"roles": {"architect": {"preferred": {"provider": "p1"}}}}
    assert _provider_for_role(providers, "architect") == "p1"
    assert _provider_for_role({}, "architect") == ""

def test_group_counts():
    tasks = [{"a": "x"}, {"a": "y"}, {"a": "x"}]
    res = _group_counts(tasks, lambda t: t["a"])
    assert res["x"] == 2
    assert res["y"] == 1
    # Test unassigned
    res2 = _group_counts([{}], lambda t: t.get("a"))
    assert res2["unassigned"] == 1

def test_provider_badge():
    item = {"provider": "p1", "model": "m1", "effort": "1h", "reason": "test"}
    html = _provider_badge(item, "badge")
    assert "badge" in html
    assert "p1/m1 1h" in html
    assert "title='test'" in html
    assert _provider_badge(None, "b") == "<em>none</em>"

def test_build_delta_section():
    delta = {
        "has_delta": True,
        "since": "2020",
        "tasks_completed": ["t1"],
        "tasks_added": ["t2"],
        "tasks_removed": ["t3"],
        "tasks_state_changed": ["t4"],
        "locks_acquired": ["t1"],
        "locks_released": ["t1"],
        "councils_new": ["t1"]
    }
    html = build_delta_section(delta)
    assert "t1" in html
    assert "t2" in html
    assert "t3" in html
    assert "t4" in html
    assert build_delta_section({"has_delta": False}) == ""

def test_build_handoff_journal_section():
    handoffs = [
        {"artifact": {"reason": "rate-limit", "task": "t1", "from_agent": "a1", "to_role": "r1", "generated": "now"}}
    ]
    html = build_handoff_journal_section(handoffs)
    assert "rate-limit" in html
    assert "t1" in html
    empty_html = build_handoff_journal_section([])
    assert 'id="handoff-journal"' in empty_html
    assert 'class="diagnostic"' in empty_html
    assert "No handoffs recorded" in empty_html

def test_build_provider_cards_section():
    providers = {
        "roles": {
            "dev": {
                "preferred": {"provider": "p1", "model": "m1"},
                "fallback": [{"provider": "p2", "model": "m2"}],
                "unavailable": [{"provider": "p3", "model": "m3"}]
            }
        }
    }
    html = build_provider_cards_section(providers)
    assert "dev" in html
    assert "p1/m1" in html
    assert "p2/m2" in html
    assert "p3/m3" in html
    empty_html = build_provider_cards_section({})
    assert 'id="providers"' in empty_html
    assert 'class="diagnostic"' in empty_html
    assert "No providers configured" in empty_html

def test_build_activity_section():
    status = {
        "tasks": {"active": [{"id": "t1", "state": "~", "role": "dev"}, {"id": "t2", "state": "~", "role": "pm"}]},
        "locks": {
            "items": [
                {"task_id": "t1", "owner": "agent1", "age_seconds": 100, "ttl_seconds": 600, "stale": False},
                {"task_id": "t2", "owner": "p1-m1-id", "age_seconds": 50, "ttl_seconds": 600, "stale": False}
            ]
        },
        "council": {"items": []}
    }
    html = build_activity_section(status, {"dev": "p1"})
    assert "t1" in html
    assert "agent1" in html
    assert "p1" in html
    assert "p1-m1" in html
    
    status2 = {"tasks": {"active": []}, "locks": {"items": []}}
    assert "No active work" in build_activity_section(status2, {})

def test_build_wiki_pages_section(tmp_path):
    """Секция получает страницы аргументом: чтение индекса — дело слоя сбора."""
    from brain_dashboard.collect.knowledge import collect_wiki

    idx_dir = tmp_path / ".brain" / "index"
    idx_dir.mkdir(parents=True)

    assert "No index found" in build_wiki_pages_section(collect_wiki(tmp_path))

    pages = [
        {"slug": "foo", "title": "Foo", "curation": "human", "protected": True},
        {"slug": "bar", "title": "", "curation": "agent", "protected": False},
        {"slug": "baz", "title": "Baz", "curation": "mixed", "protected": False},
    ]
    (idx_dir / "pages.json").write_text(json.dumps({"pages": pages}))

    html = build_wiki_pages_section(collect_wiki(tmp_path))
    assert "Foo" in html
    assert "human" in html
    assert "protected" in html
    assert "bar" in html
    assert "mixed" in html

    # битый индекс читается как «страниц нет», а не роняет страницу
    (idx_dir / "pages.json").write_text("invalid")
    assert "No pages indexed yet" in build_wiki_pages_section(collect_wiki(tmp_path))

    (idx_dir / "pages.json").write_text('{"pages": []}')
    assert "No pages indexed yet" in build_wiki_pages_section(collect_wiki(tmp_path))

def test_build_html_empty(tmp_path):
    brain = tmp_path
    (brain / "wiki").mkdir()
    status = {
        "tasks": {"active": [], "done": [], "summary": {"active_count": 0, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}}},
        "providers": {},
        "learning": {"available": False},
        "index": {"status": "none", "health": "ok", "stale": False, "stale_files": []},
        "graph": {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False, "counts": {}},
        "handoff_journal": [],
        "scheduled": {
            "summary": {"cron": 0, "systemd_timers": 0, "at": 0},
            "cron": {"status": "error", "error": "permission denied", "items": []},
            "systemd_timers": {"status": "ok", "error": "", "items": []},
            "at": {"status": "error", "error": "command not found", "items": []},
        },
        "generated_at": "now",
        "brain": str(brain)
    }
    html = build_html(status, brain, "now", False, None, "")
    assert "No active tasks" in html
    assert 'id="task-tree"' in html
    assert 'id="candidate-table"' in html
    assert "Нет готовых к запуску" in html
    assert "Index not built" in html
    assert "No lightweight blockers detected" in html
    assert "No learning data found" in html
    assert "Scheduled Work" in html
    assert "permission denied" in html
    assert 'id="command-center"' in html
    assert 'id="task-operations"' in html
    assert "Compact" in html
    assert 'href="#task-tree"' in html
    assert 'href="#launch-panel"' in html
    html_live = build_html(status, brain, "now", True, None, "")
    assert "/api/status" in html_live
    assert "brainDashboardPollSec" in html_live

def test_build_html_task_tree_candidates_fill_launch(tmp_path):
    brain = tmp_path
    (brain / "wiki").mkdir()
    status = {
        "tasks": {
            "active": [
                {"id": "t-root", "state": " ", "priority": "P1", "title": "Root task", "role": "architect", "mode": "solo", "depends_on": [], "parent": ""},
                {"id": "t-child", "state": " ", "priority": "P1", "title": "Child task", "role": "developer", "mode": "solo", "depends_on": ["t-root"], "parent": "t-root"},
                {"id": "t-blocked", "state": "!", "priority": "P2", "title": "Blocked task", "role": "reviewer", "mode": "solo", "depends_on": ["t-missing"], "parent": ""},
            ],
            "done": [
                {"id": "t-done", "state": "x", "priority": "P2", "title": "Done task", "role": "pm", "mode": "solo", "depends_on": [], "parent": ""}
            ],
            "summary": {"active_count": 3, "done_count": 1, "states": {" ": 2, "!": 1}, "priorities": {"P1": 2, "P2": 1}, "roles": {"architect": 1, "developer": 1, "reviewer": 1}, "modes": {"solo": 3}},
        },
        "providers": {
            "roles": {
                "architect": {
                    "preferred": {"provider": "codex", "model": "gpt-5.5", "command": "codex"},
                    "fallback": [{"provider": "claude", "model": "opus-4.7"}],
                    "unavailable": [],
                },
                "developer": {
                    "preferred": {"provider": "gemini", "model": "gemini-3-flash", "command": "gemini -m gemini-3-flash-preview"},
                    "fallback": [{"provider": "codex", "model": "gpt-5.3"}],
                    "unavailable": [],
                },
                "reviewer": {
                    "preferred": {"provider": "gemini", "model": "gemini-3.1-pro", "command": "gemini -m gemini-3.1-pro"},
                    "fallback": [],
                    "unavailable": [{"provider": "claude", "model": "opus-4.7", "reason": "quota"}],
                },
            }
        },
        "learning": {"available": False},
        "index": {"status": "present", "health": "ok", "stale": False, "stale_files": []},
        "graph": {"available": False},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False},
        "handoff_journal": [],
        "scheduled": {
            "summary": {"cron": 1, "systemd_timers": 1, "at": 0},
            "cron": {"status": "ok", "error": "", "items": [{"schedule": "*/15 * * * *", "command": "brain-dashboard export"}]},
            "systemd_timers": {"status": "ok", "error": "", "items": [{"next": "Fri 2026-05-29 1h left", "unit": "brain-sync.timer", "activates": "brain-sync.service"}]},
            "at": {"status": "ok", "error": "", "items": []},
        },
        "workspaces": {
            "configured": True,
            "roots": [str(tmp_path)],
            "summary": {"count": 1, "open_tasks": 2},
            "items": [
                {
                    "path": str(tmp_path / "project-a"),
                    "title": "Workspace: Project A",
                    "open_tasks": 2,
                    "next_task": {"task_id": "local-001", "priority": "P1", "title": "Review draft", "role": "lawyer", "state": "open"},
                    "latest_log": {"timestamp": "2026-05-28T10:00:00Z", "agent": "agent-a", "summary": "created"},
                }
            ],
            "error": "",
        },
        "generated_at": "now",
        "brain": str(brain),
    }

    html = build_html(status, brain, "now", False, None, "")
    assert 'id="task-tree"' in html
    assert 'id="candidate-table"' in html
    assert "Runnable Candidates" in html
    assert "Task Tree" in html
    assert "t-root" in html
    assert "t-child" in html
    assert "depends: t-root" in html
    assert "blocked: state blocked; missing: t-missing" in html
    assert "codex/gpt-5.5" in html
    assert "gemini/gemini-3-flash" in html
    assert "claude/opus-4.7" in html
    assert "data-launch-fill-task='t-root'" in html
    assert "data-launch-fill-role='architect'" in html
    assert "data-launch-fill-client='codex'" in html
    assert "brain-dashboard export" in html
    assert "brain-sync.timer" in html
    assert "Runnable now" in html
    assert "2" in html
    assert 'id="workspaces"' in html
    assert "Workspace: Project A" in html
    assert "local-001" in html
    assert f"data-launch-fill-workspace='{tmp_path / 'project-a'}'" in html
    assert "Подготовить" in html
    assert "Review draft" in html

def test_build_html_errors(tmp_path):
    brain = tmp_path
    (brain / "wiki").mkdir()
    status = {
        "tasks": {"active": [], "done": [], "summary": {"active_count": 0, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}}},
        "providers": {},
        "learning": {"available": True, "counts": {}, "recent_incidents": [], "recent_lessons": []},
        "index": {"status": "error", "health": "error", "error": "test error"},
        "graph": {"available": False},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False},
        "handoff_journal": [],
        "generated_at": "now",
        "brain": str(brain)
    }
    html = build_html(status, brain, "now", False, None, "")
    assert "test error" in html
    assert "No incidents yet" in html
    assert "No lessons yet" in html

def test_build_html_items(tmp_path, monkeypatch):
    brain = tmp_path
    idx_dir = tmp_path / ".brain" / "index"
    idx_dir.mkdir(parents=True)
    (brain / "wiki").mkdir()
    (brain / "wiki" / "log.md").write_text("## [now] op | t1 | a1 | extra\n")
    
    status = {
        "tasks": {
            "active": [{"id": "t1", "state": " ", "priority": "P1", "title": "T1", "role": "dev"}],
            "done": [],
            "summary": {"active_count": 1, "done_count": 0, "states": {" ": 1}, "priorities": {"P1": 1}, "roles": {"dev": 1}, "modes": {"solo": 1}}
        },
        "providers": {},
        "learning": {
            "available": True,
            "counts": {"incidents": 1, "pending": 1, "approved": 1, "active": 1, "deprecated": 1},
            "recent_incidents": [{"id": "i1", "source": "s1", "severity": "S1", "task_id": "t1", "created": "now"}],
            "recent_lessons": [
                {"id": "L1", "status": "active", "roles": ["dev"], "severity": "S1", "source": "s1", "confidence": "high", "context_tokens_est": 100, "injectable": True},
                {"id": "L2", "status": "rejected", "roles": "pm", "severity": "S1", "source": "s1", "confidence": "low", "context_tokens_est": 0, "injectable": False}
            ],
            "injection_policy": {}
        },
        "index": {"status": "present", "health": "stale", "generated_at": "now", "page_count": 1, "raw_count": 1, "link_count": 1, "search_docs": 1, "stale_files": ["f1"]},
        "graph": {"available": True, "nodes": 1, "edges": 1, "node_types": {"a": 1}, "edge_types": {"b": 1}},
        "tokens": {
            "available": True,
            "aggregate": {"commands": 1, "raw_tokens_est": 100, "compact_tokens_est": 50, "savings_percent": 50},
            "recent": [{"ts": "now", "kind": "k1", "provider": "p1", "role": "r1", "session": "s1", "raw_tokens_est": 100, "compact_tokens_est": 50, "savings_percent": 50, "raw_artifact": "a1"}]
        },
        "locks": {"count": 1, "stale_count": 1, "items": [{"task_id": "t1", "owner": "a1", "stale": True}]},
        "council": {
            "count": 1, 
            "items": [
                {"task_id": "t1", "roles_required": ["r1"], "opinions": [{"role": "r1", "status": "valid"}], "synthesis": {"status": "ready", "ready": True}, "file_count": 1, "files": ["f1.md"]}
            ]
        },
        "handoff": {"exists": True, "reason": "limit", "commands": ["cmd1"]},
        "handoff_journal": [],
        "generated_at": "now",
        "brain": str(brain)
    }
    
    html = build_html(status, brain, "now", False, None, "")
    assert "i1" in html
    assert "L1" in html
    assert "rejected" in html
    assert "index health: stale" in html
    assert "f1" in html
    assert "cmd1" in html
    assert "k1" in html
    assert "nodes" in html
    assert '<pre id="launch-output" class="launch-output kb-output" aria-live="polite"></pre>' in html
    assert '<pre id="task-action-output" class="task-action-output kb-output" aria-live="polite"></pre>' in html


def test_dashboard_output_boxes_use_prominent_styling():
    from brain_dashboard.render.assets import TASK_OPS_SCRIPT, SSE_SCRIPT

    # единый вывод результата операций
    assert 'task-action-output' in TASK_OPS_SCRIPT
    assert "scrollIntoView" in TASK_OPS_SCRIPT

    assert "showActionResult" in SSE_SCRIPT
    assert "task-action-output" in SSE_SCRIPT
    assert "reloadAfterFeedback" in SSE_SCRIPT
    assert "actionSuccessMessage" in SSE_SCRIPT
    assert "Задача завершена" in SSE_SCRIPT


def test_launch_fill_opens_manual_launch_and_shows_feedback():
    from brain_dashboard.render.assets import LAUNCH_SCRIPT

    assert 'document.querySelector("details.manual-launch")' in LAUNCH_SCRIPT
    assert "manual.open=true" in LAUNCH_SCRIPT
    assert 'manual.scrollIntoView({behavior:"smooth",block:"center"})' in LAUNCH_SCRIPT
    assert "поля заполнены" in LAUNCH_SCRIPT
    assert "launch-output" in LAUNCH_SCRIPT


def test_search_results_xss_protection():
    from brain_dashboard.render.assets import SEARCH_SCRIPT as generated_script

    malicious_result = '<img src=x onerror=alert(1)>'

    assert "pathTd.textContent = r.path;" in generated_script
    assert "strong.textContent = r.title;" in generated_script
    assert 'span.textContent = r.snippet || "";' in generated_script
    assert 'scoreTd.textContent = score.toFixed(4) + " (" + label + ")";' in generated_script

    assert "html +=" not in generated_script
    assert "resDiv.innerHTML = html" not in generated_script
    assert "r.path +" not in generated_script
    assert "r.title +" not in generated_script
    assert "r.snippet +" not in generated_script
    assert malicious_result not in generated_script

    assert 'timeoutSpan.textContent = "Поиск занял слишком долго";' in generated_script
    assert 'errorSpan.textContent = "Error: " + e;' in generated_script


def test_surface_badge_helper():
    """_surface_badge returns a badge span for the given surface (t-2026-06-26-dashboard-badge)."""
    from brain_dashboard.render.utils import _surface_badge
    html_i = _surface_badge("interactive")
    assert "interactive" in html_i
    assert "badge" in html_i
    html_h = _surface_badge("headless")
    assert "headless" in html_h
    assert "badge" in html_h


def test_build_html_surface_badge_in_task_row(tmp_path):
    """Task rows must contain a surface badge (t-2026-06-26-dashboard-badge)."""
    brain = tmp_path
    (brain / "wiki").mkdir()
    status = {
        "tasks": {
            "active": [
                {
                    "id": "t-hdl", "state": " ", "priority": "P1", "title": "Headless",
                    "role": "developer", "mode": "solo", "depends_on": [], "parent": "",
                    "surface": "headless",
                },
                {
                    "id": "t-int", "state": " ", "priority": "P1", "title": "Interactive",
                    "role": "designer", "mode": "solo", "depends_on": [], "parent": "",
                    "surface": "interactive",
                },
            ],
            "done": [],
            "summary": {
                "active_count": 2, "done_count": 0,
                "states": {" ": 2}, "priorities": {"P1": 2},
                "roles": {"developer": 1, "designer": 1}, "modes": {"solo": 2},
                "surfaces": {"headless": 1, "interactive": 1},
            },
        },
        "providers": {},
        "learning": {"available": False},
        "index": {"status": "none", "health": "ok", "stale": False, "stale_files": []},
        "graph": {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False, "counts": {}},
        "handoff_journal": [],
        "scheduled": {
            "summary": {"cron": 0, "systemd_timers": 0, "at": 0},
            "cron": {"status": "error", "error": "no cron", "items": []},
            "systemd_timers": {"status": "ok", "error": "", "items": []},
            "at": {"status": "error", "error": "no at", "items": []},
        },
        "generated_at": "now",
        "brain": str(brain),
    }
    html = build_html(status, brain, "now", False, None, "")
    # surface badge must appear in the task rows
    assert "surface" in html
    assert "headless" in html
    assert "interactive" in html
    # open window affordance for interactive task
    assert "↗" in html



# --- t-2026-06-29-ui-h3-hierarchy ---
def test_h3_not_muted():
    """h3 must not use var(--muted); should use a brighter color (t-2026-06-29-ui-h3-hierarchy)."""
    from brain_dashboard.render.assets import CSS
    # The h3 rule must not be de-emphasized with --muted
    import re
    m = re.search(r'h3\s*\{[^}]*\}', CSS)
    assert m, "h3 rule not found in CSS"
    rule = m.group(0)
    assert 'var(--muted)' not in rule, f"h3 still uses var(--muted): {rule}"
    # Must use a bright color (#d6dbe0 or var(--text))
    assert '#d6dbe0' in rule or 'var(--text)' in rule, f"h3 has no bright color: {rule}"


# --- t-2026-06-29-ui-active-tab-affordance ---
def test_active_tab_has_accent_affordance():
    """Active tab must have font-weight:600 and bottom accent shadow (t-2026-06-29-ui-active-tab-affordance)."""
    from brain_dashboard.render.assets import TAB_CSS
    import re
    m = re.search(r'\.tab-btn\.active\{[^}]*\}', TAB_CSS)
    assert m, ".tab-btn.active rule not found in TAB_CSS"
    rule = m.group(0)
    assert 'font-weight:600' in rule, f".tab-btn.active missing font-weight:600: {rule}"
    assert 'box-shadow' in rule, f".tab-btn.active missing box-shadow accent: {rule}"
    assert 'inset 0 -2px 0' in rule, f".tab-btn.active box-shadow should be bottom bar: {rule}"
    # must not use side borders wider than 1px (anti-pattern)
    assert 'border-left' not in rule and 'border-right' not in rule, f"Side border anti-pattern in: {rule}"


# --- t-2026-06-29-dashboard-project-tabs ---
from brain_dashboard.render.workspaces import _build_project_tabs, _render_ws_panel


def test_project_tabs_empty():
    tabbar, panels = _build_project_tabs([])
    assert 'data-tab-target="brain"' in tabbar
    assert 'data-tab-target="ws-empty"' in tabbar  # hint tab when none configured
    assert "ws-empty" in panels


def test_project_tabs_with_workspaces():
    items = [{"title": "Alpha", "path": "/p/alpha",
              "tasks": [{"state": "open", "priority": "P1", "task_id": "t-a",
                         "title": "do", "role": "developer"}],
              "log_entries": [], "warnings": []}]
    tabbar, panels = _build_project_tabs(items)
    assert 'data-tab-target="ws-0"' in tabbar and "Alpha" in tabbar
    assert 'data-tab="ws-0"' in panels and "t-a" in panels


def test_ws_panel_escapes_and_fields():
    panel = _render_ws_panel("ws-0", {"title": "P<x>", "path": "/p", "tasks": [],
                                       "log_entries": [], "warnings": ["w1"]})
    assert "P&lt;x&gt;" in panel and "нет задач в TASKS.md" in panel and "w1" in panel


def test_ws_panel_full_view_board_and_activity():
    it = {"title": "Alpha", "path": "/p", "warnings": [],
          "tasks": [
              {"state": "in-progress", "priority": "P1", "task_id": "t-2", "title": "refactor", "role": "developer"},
              {"state": "open", "priority": "P2", "task_id": "t-1", "title": "ci", "role": "developer"},
              {"state": "done", "priority": "P2", "task_id": "t-0", "title": "init", "role": "developer"},
          ],
          "log_entries": [{"timestamp": "2026-06-29T03:10:00Z", "agent": "dev-1", "summary": "started"}]}
    panel = _render_ws_panel("ws-0", it)
    assert "in-progress" in panel and "t-2" in panel
    assert "open" in panel and "Activity" in panel and "started" in panel
    assert "t-0" not in panel  # done tasks counted, not listed in board


def test_short_path_truncates():
    from brain_dashboard.render.parts import _short_path
    assert _short_path("/home/user/Документы/Альфа") == "…/Документы/Альфа"
    assert _short_path("/only") == "/only"
    assert _short_path("") == ""


def test_ws_panel_path_has_title_full_and_short_visible():
    from brain_dashboard.render.workspaces import _render_ws_panel
    panel = _render_ws_panel("ws-0", {"title": "P", "path": "/home/user/projects/acme",
                                      "tasks": [], "log_entries": [], "warnings": []})
    assert 'title="/home/user/projects/acme"' in panel   # full path on hover
    assert "…/projects/acme" in panel                      # short visible


def test_table_zebra_visible():
    from brain_dashboard.render.assets import CSS
    assert "rgba(255, 255, 255, .045)" in CSS
    assert "rgba(255, 255, 255, .018)" not in CSS


def test_board_state_color_coded():
    from brain_dashboard.render.workspaces import _render_ws_panel
    it = {"title": "P", "path": "/p", "log_entries": [], "warnings": "",
          "tasks": [{"state": "in-progress", "priority": "P1", "task_id": "t-2", "title": "x", "role": "dev"},
                    {"state": "blocked", "priority": "P1", "task_id": "t-3", "title": "y", "role": "dev"}]}
    panel = _render_ws_panel("ws-0", it)
    assert "var(--cyan-fg)" in panel   # in-progress
    assert "var(--red-fg)" in panel    # blocked


# --- единый блок операций + проектные задачи только на вкладках проектов ---

def _minimal_status(brain, workspaces=None):
    status = {
        "tasks": {"active": [], "done": [], "summary": {"active_count": 0, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}}},
        "providers": {},
        "learning": {"available": False},
        "index": {"status": "none", "health": "ok", "stale": False, "stale_files": []},
        "graph": {"available": False, "nodes": 0, "edges": 0, "node_types": {}, "edge_types": {}},
        "tokens": {"available": False},
        "locks": {"count": 0, "stale_count": 0, "items": []},
        "council": {"count": 0, "items": []},
        "handoff": {"active": False, "counts": {}},
        "handoff_journal": [],
        "scheduled": {
            "summary": {"cron": 0, "systemd_timers": 0, "at": 0},
            "cron": {"status": "ok", "error": "", "items": []},
            "systemd_timers": {"status": "ok", "error": "", "items": []},
            "at": {"status": "ok", "error": "", "items": []},
        },
        "generated_at": "now",
        "brain": str(brain),
    }
    if workspaces is not None:
        status["workspaces"] = workspaces
    return status


def test_task_operations_single_block(tmp_path):
    """Все операции с задачами — внутри одного блока #task-operations на вкладке brain."""
    (tmp_path / "wiki").mkdir()
    html = build_html(_minimal_status(tmp_path), tmp_path, "now", False, None, "")
    assert 'id="task-operations"' in html
    block = html[html.index('id="task-operations"'):html.index('class="secondary-group"')]
    for anchor in ('id="task-filters"', 'class="manual-launch"',
                   'id="launch-panel"', 'id="task-action-output"'):
        assert anchor in block, f"{anchor} must be inside #task-operations"
    # старых секций больше нет
    for gone in ('id="action-board"', 'id="board"', 'id="queue-autopilot"'):
        assert gone not in html
    # диагностическая таблица кандидатов больше не содержит кнопок запуска
    task_tree = html[html.index('id="task-tree"'):]
    assert "data-launch-fill" not in task_tree.split("</section>")[0]


def test_project_tasks_only_on_project_tabs(tmp_path):
    """Задачи проектов не отображаются на вкладке brain — только на вкладках проектов."""
    (tmp_path / "wiki").mkdir()
    workspaces = {
        "configured": True,
        "roots": [str(tmp_path)],
        "summary": {"count": 1, "open_tasks": 2},
        "items": [
            {
                "path": str(tmp_path / "project-a"),
                "title": "Workspace: Project A",
                "open_tasks": 2,
                "next_task": {"task_id": "proj-101", "priority": "P1", "title": "Review draft", "role": "lawyer", "state": "open"},
                "latest_log": {"timestamp": "2026-05-28T10:00:00Z", "agent": "agent-a", "summary": "created"},
                "tasks": [
                    {"state": "open", "priority": "P1", "task_id": "proj-101", "title": "Review draft", "role": "lawyer"},
                    {"state": "in-progress", "priority": "P2", "task_id": "proj-102", "title": "Collect docs", "role": "paralegal"},
                ],
                "log_entries": [],
                "warnings": [],
            }
        ],
        "error": "",
    }
    html = build_html(_minimal_status(tmp_path, workspaces), tmp_path, "now", False, None, "")
    brain_panel = html[html.index('data-tab="brain"'):html.index('data-tab="ws-0"')]
    assert "proj-101" not in brain_panel
    assert "proj-102" not in brain_panel
    assert "Workspace-задачи" not in html
    ws_panel = html[html.index('data-tab="ws-0"'):]
    assert "proj-101" in ws_panel and "proj-102" in ws_panel
    assert f"data-launch-fill-workspace='{tmp_path / 'project-a'}'" in ws_panel


def test_ws_panel_prepare_buttons():
    """Панель проекта содержит операции «Подготовить» для незакрытых задач."""
    it = {"title": "P", "path": "/p", "log_entries": [], "warnings": [],
          "tasks": [
              {"state": "open", "priority": "P1", "task_id": "t-a", "title": "x", "role": "developer"},
              {"state": "done", "priority": "P2", "task_id": "t-b", "title": "y", "role": "developer"},
          ]}
    panel = _render_ws_panel("ws-0", it)
    assert "data-launch-fill-task='t-a'" in panel
    assert "data-launch-fill-workspace='/p'" in panel
    assert "Подготовить" in panel
    assert "data-launch-fill-task='t-b'" not in panel  # done — без операций


def test_launch_fill_uses_form_in_same_panel():
    """«Подготовить» заполняет форму ручного запуска своей вкладки (без переключения)."""
    from brain_dashboard.render.assets import LAUNCH_SCRIPT
    assert 'fill.closest?fill.closest(".tab-panel")' in LAUNCH_SCRIPT
    assert 'panel.querySelector("details.manual-launch")' in LAUNCH_SCRIPT
    assert 'document.querySelectorAll("details.manual-launch").forEach(bindForm)' in LAUNCH_SCRIPT


# --- редизайн управления задачами: группы по готовности, автопилот в карточках ---

def test_task_ops_groups_by_readiness(tmp_path):
    """Задачи распределяются по группам: готовы / в работе / заблокированы."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path)
    status["tasks"] = {
        "active": [
            {"id": "t-ready", "state": " ", "priority": "P1", "title": "Ready", "role": "developer", "mode": "solo", "depends_on": [], "parent": ""},
            {"id": "t-run", "state": "~", "priority": "P1", "title": "Running", "role": "lawyer", "mode": "solo", "depends_on": [], "parent": ""},
            {"id": "t-blk", "state": "!", "priority": "P2", "title": "Stuck", "role": "reviewer", "mode": "solo", "depends_on": ["t-missing"], "parent": ""},
        ],
        "done": [],
        "summary": {"active_count": 3, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    ready = html[html.index("id='task-ops-ready'"):html.index("id='task-ops-progress'")]
    progress = html[html.index("id='task-ops-progress'"):html.index("id='task-ops-blocked'")]
    blocked = html[html.index("id='task-ops-blocked'"):]
    assert "t-ready" in ready and "▶ Запустить" in ready and "data-kb-action='dry-run'" in ready
    assert "data-action='take'" in ready
    assert "t-run" in progress and "data-action='complete'" in progress and "data-action='release'" in progress
    assert "t-blk" in blocked and "блокеры" in blocked and "missing: t-missing" in blocked
    # у заблокированных нет кнопки боевого запуска
    assert "▶ Запустить" not in blocked.split("</details>")[0]


def test_task_ops_autopilot_merged_into_cards(tmp_path):
    """Pending-предложение автопилота отображается бейджем на карточке задачи."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path)
    status["tasks"] = {
        "active": [{"id": "t-auto", "state": " ", "priority": "P1", "title": "Auto", "role": "developer", "mode": "solo", "depends_on": [], "parent": ""}],
        "done": [],
        "summary": {"active_count": 1, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    status["queue_autopilot"] = {
        "available": True,
        "proposals": [
            {"id": "prop-1", "task": "t-auto", "title": "Auto", "role": "developer",
             "priority": "P1", "client": "gemini", "status": "pending", "workspace": ""},
            {"id": "prop-2", "task": "t-other", "title": "Other", "role": "developer",
             "priority": "P2", "client": "codex", "status": "done", "workspace": ""},
        ],
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    assert "автопилот" in html
    assert "data-kb-proposal='prop-1'" in html
    assert 'id="queue-autopilot"' not in html  # отдельной секции больше нет
    # клиент из предложения выбран в селекте карточки
    card = html[html.index("data-kb-proposal='prop-1'") - 2000:html.index("data-kb-proposal='prop-1'")]
    assert "<option value='gemini' selected>" in card


def test_task_ops_cycles_fold(tmp_path):
    """Циклические brain-таймеры — свёрнутая группа внутри блока операций."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path)
    status["scheduled"]["systemd_timers"]["items"] = [
        {"next": "Fri 2026-07-10", "unit": "brain-sync.timer", "activates": "brain-sync.service"},
        {"next": "Sat", "unit": "other.timer", "activates": "other.service"},
    ]
    html = build_html(status, tmp_path, "now", False, None, "")
    fold = html[html.index("id='task-ops-cycles'"):]
    fold = fold[:fold.index("</details>")]
    assert "data-kb-action='cycle-run'" in fold and "brain-sync.timer" in fold
    assert "other.timer" not in fold  # не-brain таймеры не операционные


def test_ws_panel_cards_have_launch_operations():
    """Карточки задач проекта имеют прямой запуск и dry-run со своим workspace."""
    it = {"title": "P", "path": "/p", "log_entries": [], "warnings": [],
          "tasks": [{"state": "open", "priority": "P1", "task_id": "t-a", "title": "x", "role": "developer"}]}
    panel = _render_ws_panel("ws-0", it)
    assert "data-kb-action='launch'" in panel
    assert "data-kb-action='dry-run'" in panel
    assert "data-kb-workspace='/p'" in panel
    assert "select" in panel and "task-client" in panel


def test_ws_panel_full_control_panel():
    """Каждая вкладка проекта — полноценная панель: фильтры, ручной запуск, свой вывод."""
    it = {"title": "P", "path": "/p", "log_entries": [], "warnings": [],
          "tasks": [{"state": "open", "priority": "P1", "task_id": "t-a", "title": "x", "role": "developer"}]}
    panel = _render_ws_panel("ws-0", it)
    assert 'class="task-filters filter-row"' in panel
    assert 'class="manual-launch"' in panel
    assert 'value="/p"' in panel  # workspace предзаполнен путём проекта
    assert "task-action-output" in panel
    assert "data-filter-row='task'" in panel  # карточки фильтруются локально


def test_filter_script_scoped_per_panel():
    """Фильтры действуют только в своей секции (не через вкладки)."""
    from brain_dashboard.render.assets import FILTER_SCRIPT
    assert 'box.closest("section")' in FILTER_SCRIPT
    assert 'scope.querySelectorAll("[data-filter-row=task]")' in FILTER_SCRIPT


# --- привязка задач очереди Brain к проектам (project: <имя папки>) ---

def _ws_alpha(tmp_path):
    return {
        "configured": True,
        "roots": [str(tmp_path)],
        "summary": {"count": 1, "open_tasks": 0},
        "items": [{"path": "/p/alpha", "title": "Workspace: Alpha", "open_tasks": 0,
                   "next_task": {}, "latest_log": {}, "tasks": [], "log_entries": [], "warnings": []}],
        "error": "",
    }


def test_root_queue_project_field_does_not_move_task(tmp_path):
    """project: в корневой очереди больше не уводит задачу на вкладку проекта."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path, _ws_alpha(tmp_path))
    status["tasks"] = {
        "active": [
            {"id": "t-proj", "state": " ", "priority": "P1", "title": "Proj task",
             "role": "lawyer", "mode": "solo", "depends_on": [], "parent": "",
             "project": "alpha", "raw": "- [ ] [P1] t-proj — Proj task\n      project: alpha\n"},
            {"id": "t-brain", "state": " ", "priority": "P2", "title": "Brain task",
             "role": "developer", "mode": "solo", "depends_on": [], "parent": "", "raw": ""},
        ],
        "done": [],
        "summary": {"active_count": 2, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    brain_panel = html[html.index('data-tab="brain"'):html.index('data-tab="ws-0"')]
    ws_panel = html[html.index('data-tab="ws-0"'):]
    assert "t-proj" in brain_panel
    assert "t-brain" in brain_panel
    assert "Очередь Brain" not in ws_panel
    assert "t-proj" not in ws_panel


def test_project_field_unmatched_stays_on_brain(tmp_path):
    """project: без вкладки — задача остаётся в brain; бейдж проекта по-прежнему виден."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path, _ws_alpha(tmp_path))
    status["tasks"] = {
        "active": [
            {"id": "t-ghost", "state": " ", "priority": "P1", "title": "Ghost",
             "role": "developer", "mode": "solo", "depends_on": [], "parent": "",
             "project": "ghost", "raw": "- [ ] t-ghost\n      project: ghost\n"},
        ],
        "done": [],
        "summary": {"active_count": 1, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    brain_panel = html[html.index('data-tab="brain"'):html.index('data-tab="ws-0"')]
    assert "t-ghost" in brain_panel
    assert "📁 ghost" in brain_panel


def test_project_tab_has_no_root_queue_badge(tmp_path):
    """Вкладка проекта не считает задачи корневой очереди по полю project:."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path, _ws_alpha(tmp_path))
    status["tasks"] = {
        "active": [
            {"id": "t-proj", "state": " ", "priority": "P1", "title": "Proj task",
             "role": "lawyer", "mode": "solo", "depends_on": [], "parent": "",
             "project": "Workspace: Alpha", "raw": "project: Workspace: Alpha"},
        ],
        "done": [],
        "summary": {"active_count": 1, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    tabbar = html[html.index('class="tabbar"'):html.index('data-tab="brain"')]
    assert "<span class='badge'>1</span>" not in tabbar


def test_task_stats_has_no_client_bucket(tmp_path):
    """Сводка «active by client» снята вместе с агрегацией clients."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path)
    status["tasks"]["summary"]["clients"] = {"ООО Ромашка": 1}
    html = build_html(status, tmp_path, "now", False, None, "")
    assert "active by client" not in html
    assert "task-group-client" not in html


# --- переключатель режима запуска: интерактив / фон ---

def test_launch_mode_select_on_cards(tmp_path):
    """У готовых задач есть выбор режима запуска; по умолчанию — из surface."""
    (tmp_path / "wiki").mkdir()
    status = _minimal_status(tmp_path)
    status["tasks"] = {
        "active": [
            {"id": "t-int", "state": " ", "priority": "P1", "title": "Int", "role": "product",
             "mode": "solo", "depends_on": [], "parent": "", "surface": "interactive"},
            {"id": "t-bg", "state": " ", "priority": "P2", "title": "Bg", "role": "developer",
             "mode": "solo", "depends_on": [], "parent": "", "surface": "headless"},
        ],
        "done": [],
        "summary": {"active_count": 2, "done_count": 0, "states": {}, "priorities": {}, "roles": {}, "modes": {}},
    }
    html = build_html(status, tmp_path, "now", False, None, "")
    int_card = html[html.index("data-mode-key='t-int'"):]
    int_card = int_card[:int_card.index("</select>")]
    bg_card = html[html.index("data-mode-key='t-bg'"):]
    bg_card = bg_card[:bg_card.index("</select>")]
    assert "value='interactive' selected" in int_card
    assert "value='background' selected" in bg_card
    assert "интерактив" in int_card and "фон" in bg_card


def test_launch_mode_passed_to_api():
    """Скрипты передают mode в /api/launch и в запуск предложений."""
    from brain_dashboard.render.assets import TASK_OPS_SCRIPT, LAUNCH_SCRIPT
    assert "modeFor(btn)" in TASK_OPS_SCRIPT
    assert '"&mode=" + encodeURIComponent(mode)' in TASK_OPS_SCRIPT
    assert '"taskMode:"' in TASK_OPS_SCRIPT  # выбор запоминается
    assert '.launch-mode' in LAUNCH_SCRIPT
    assert '"&mode="+encodeURIComponent(mode)' in LAUNCH_SCRIPT


def test_manual_launch_has_mode_select():
    from brain_dashboard.render.parts import _render_manual_launch
    form = _render_manual_launch(workspace_default="/b", with_ids=True)
    assert 'id="launch-mode"' in form
    assert 'class="launch-mode"' in form
    assert "интерактив" in form and "фон" in form


def test_launch_form_loads_models_for_selected_cli():
    """«Подготовить» вызывает CLI: проверка доступности + актуальные модели в меню выбора."""
    from brain_dashboard.render.assets import LAUNCH_SCRIPT
    from brain_dashboard.render.parts import _render_manual_launch
    assert '/api/models?client=' in LAUNCH_SCRIPT
    assert "loadModels(manual)" in LAUNCH_SCRIPT       # при «Подготовить»
    assert 'clientSel.addEventListener("change"' in LAUNCH_SCRIPT  # при смене CLI
    assert 'select.launch-model' in LAUNCH_SCRIPT       # модели — в меню выбора
    assert "авто (по роли)" in LAUNCH_SCRIPT
    assert "✓ доступен" in LAUNCH_SCRIPT and "✗ CLI не найден" in LAUNCH_SCRIPT
    form = _render_manual_launch(with_ids=True)
    assert '<select id="launch-model" class="launch-model"' in form


def test_prepare_defaults_to_interactive_mode():
    """«Подготовить» ставит режим «интерактив» — запуск может требовать логина CLI."""
    from brain_dashboard.render.assets import LAUNCH_SCRIPT
    assert 'set(".launch-mode","interactive")' in LAUNCH_SCRIPT
    assert "требуется логин" in LAUNCH_SCRIPT  # подсказка при молчащем --version


def test_build_html_has_no_free_names():
    """Ни одно имя в build_html не должно приходить «ниоткуда».

    При выносе секций из build_html две переменные (release_label,
    release_blockers) остались вычисляться внутри вынесенной функции, а
    читаться — снаружи. Юнит-тесты этого не поймали: строка лежала в ветке,
    которую они не проходят, и падало только на живом экспорте. Проверка
    статическая, поэтому ловит такие следы независимо от покрытия.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "runtime/lib/brain_dashboard/render/html.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    import builtins

    known = set(dir(builtins)) | {
        "len", "sum", "sorted", "str", "int", "list", "dict", "set", "any", "all", "min", "max",
        "enumerate", "range", "bool", "float", "isinstance", "getattr", "reversed", "zip",
        "Path", "Any",
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            known.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            known |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            known.add(node.targets[0].id)

    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_html")
    assigned = {a.arg for a in fn.args.args}
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            assigned.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            assigned |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.comprehension) and isinstance(n.target, ast.Name):
            assigned.add(n.target.id)
    read = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}

    assert sorted(read - assigned - known) == []
