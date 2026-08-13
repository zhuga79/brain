"""Диагностические секции страницы.

Каждая из них — самостоятельный кусок HTML, собранный из своей части статуса:
статистика задач, локи, совет, индекс, граф, ворота релиза, представления
Obsidian, экономия токенов, обучение и журнал операций. Раньше они лежали
подряд внутри build_html, и функция на 610 строк была не сборкой страницы, а
её содержимым.

Каждая функция принимает ровно то, что читает, — по списку параметров видно,
от какой части статуса секция зависит.
"""

from __future__ import annotations

from typing import Any

from .labels import STATE_LABELS
from .utils import h, counter_table, _group_counts


def build_task_stats(active_tasks: Any, done_tasks: Any, provider_by_role: Any, summary: Any) -> str:
    active_by_role = _group_counts(active_tasks, lambda t: t.get("role") or "unassigned")
    active_by_provider = _group_counts(active_tasks, lambda t: provider_by_role.get(t.get("role") or "", "") or "unassigned")
    done_by_role = _group_counts(done_tasks, lambda t: t.get("role") or "unassigned")
    done_by_provider = _group_counts(done_tasks, lambda t: provider_by_role.get(t.get("role") or "", "") or "unassigned")
    task_stats_section = f"""
<section id="task-stats" class="diagnostic">
  <h2>Статистика задач</h2>
  <div class="summary-row">
    <div class="card"><strong>by state</strong><br>{counter_table(summary['states'], STATE_LABELS)}</div>
    <div class="card"><strong>by priority</strong><br>{counter_table(summary['priorities'])}</div>
    <div class="card"><strong>by mode</strong><br>{counter_table(summary['modes'])}</div>
    <div id="task-group-role" class="card"><strong>active by role</strong><br>{counter_table(active_by_role)}</div>
    <div id="task-group-provider" class="card"><strong>active by provider</strong><br>{counter_table(active_by_provider)}</div>
  </div>
  <h3>История (выполнено)</h3>
  <div class="summary-row">
    <div id="done-group-role" class="card"><strong>done by role</strong><br>{counter_table(done_by_role)}</div>
    <div id="done-group-provider" class="card"><strong>done by provider</strong><br>{counter_table(done_by_provider)}</div>
  </div>
</section>"""
    return task_stats_section


def build_locks(locks: Any, status: Any) -> str:
    lock_rows = ""
    for lock in locks:
        stale = lock.get("stale")
        stale_label = "✗ stale" if stale is True else ("ok" if stale is False else "?")
        stale_cls = "stale" if stale is True else ""
        age = lock.get("age_seconds")
        ttl = lock.get("ttl_seconds")
        lock_rows += (
            f"<tr class='{h(stale_cls)}'>"
            f"<td class='mono'>{h(lock['task_id'])}</td>"
            f"<td>{h(lock['owner'] or '—')}</td>"
            f"<td>{h(f'{age}s' if age is not None else '—')}</td>"
            f"<td>{h(f'{ttl}s' if ttl is not None else '—')}</td>"
            f"<td>{h(stale_label)}</td>"
            f"</tr>"
        )
    if not lock_rows:
        lock_rows = "<tr><td colspan='5'><em>No locks</em></td></tr>"

    stale_count = status["locks"]["stale_count"]
    stale_badge = (
        f"<span class='badge stale'>{h(stale_count)} stale</span>"
        if stale_count > 0 else ""
    )
    locks_section = f"""
<section id="locks" class="diagnostic">
  <h2>Locks <span id="sse-locks-stale">{stale_badge}</span></h2>
  <p>Total: <span id="sse-locks-count">{h(status['locks']['count'])}</span></p>
  <table>
    <tr><th>Task ID</th><th>Owner</th><th>Age</th><th>TTL</th><th>Status</th></tr>
    {lock_rows}
  </table>
</section>"""
    return locks_section


def build_council(councils: Any, status: Any) -> str:
    council_rows = ""
    for c in councils:
        opinions = c.get("opinions", [])
        opinion_badges = []
        for op in opinions:
            status_name = op.get("status", "missing")
            cls = {
                "valid": "state-done",
                "invalid": "state-blocked",
                "missing": "state-progress",
            }.get(status_name, "")
            label = f"{op.get('role', '')}: {status_name}"
            opinion_badges.append(f"<span class='badge {cls}'>{h(label)}</span>")
        synthesis = c.get("synthesis", {})
        synthesis_status = synthesis.get("status", "not_ready")
        synth_cls = {
            "done": "state-done",
            "ready": "state-progress",
            "not_ready": "state-blocked",
        }.get(synthesis_status, "")
        council_rows += (
            f"<tr>"
            f"<td class='mono'>{h(c['task_id'])}</td>"
            f"<td>{''.join(opinion_badges) if opinion_badges else '<em>none</em>'}</td>"
            f"<td><span class='badge {h(synth_cls)}'>{h(synthesis_status)}</span></td>"
            f"<td>{h(c['file_count'])}</td>"
            f"<td class='mono small'>{h(', '.join(c['files']))}</td>"
            f"</tr>"
        )
    if not council_rows:
        council_rows = "<tr><td colspan='5'><em>No council sessions</em></td></tr>"

    council_section = f"""
<section id="council" class="diagnostic">
  <h2>Council Sessions</h2>
  <p>Active sessions: <span id="sse-council-count">{h(status['council']['count'])}</span></p>
  <table>
    <tr><th>Task ID</th><th>Opinion Status</th><th>Synthesis</th><th>Files</th><th>File List</th></tr>
    {council_rows}
  </table>
</section>"""
    return council_section


def index_health_of(index: Any) -> str:
    """Здоровье индекса: его читают и секция индекса, и ворота релиза."""
    return index.get("health", index.get("status", "unknown"))


def build_index(index: Any) -> str:
    index_status_str = index.get("status", "unknown")
    index_health = index_health_of(index)
    health_badge_cls = {"ok": "state-done", "stale": "state-blocked", "missing": "state-blocked", "error": "state-blocked"}.get(index_health, "")
    health_badge = f"<span class='badge {health_badge_cls}'>{h(index_health)}</span>"
    if index_status_str == "present":
        stale_warn = ""
        if index.get("stale_files"):
            sf = index["stale_files"]
            stale_warn = (f"<p class='error'>⚠ {len(sf)} stale file(s): "
                          f"{h(', '.join(sf[:5]))}{'...' if len(sf) > 5 else ''} "
                          f"— run <code>brain-index rebuild</code></p>")
        index_details = (
            stale_warn
            + f"<ul>"
            f"<li>Generated at: {h(index.get('generated_at', '—'))}</li>"
            f"<li>Pages: {h(index.get('page_count', 0))}</li>"
            f"<li>Raw sources: {h(index.get('raw_count', 0))}</li>"
            f"<li>Links: {h(index.get('link_count', 0))}</li>"
            f"<li>Search docs: {h(index.get('search_docs', 0))}</li>"
            f"</ul>"
        )
    elif index_status_str == "error":
        index_details = (f"<p class='error'>Error: {h(index.get('error', ''))}</p>"
                         f"<p>→ Run <code>brain-index rebuild</code></p>")
    else:
        index_details = "<p><em>Index not built.</em> → Run <code>brain-index rebuild</code></p>"

    index_section = f"""
<section id="index" class="diagnostic">
  <h2>Machine Index {health_badge}</h2>
  <p>Status: <strong>{h(index_status_str)}</strong></p>
  {index_details}
</section>"""
    return index_section


def build_graph(status: Any) -> str:
    graph_data = status.get("graph", {})
    if graph_data.get("available"):
        node_type_rows = "".join(
            f"<tr><td>{h(t)}</td><td>{h(c)}</td></tr>"
            for t, c in graph_data.get("node_types", {}).items()
        )
        edge_type_rows = "".join(
            f"<tr><td>{h(t)}</td><td>{h(c)}</td></tr>"
            for t, c in graph_data.get("edge_types", {}).items()
        )
        graph_section = f"""
<section id="knowledge-graph" class="diagnostic">
  <h2>Knowledge Graph</h2>
  <div class="summary-row">
    <div class="card"><strong>{h(graph_data.get('nodes', 0))}</strong><br>nodes</div>
    <div class="card"><strong>{h(graph_data.get('edges', 0))}</strong><br>edges</div>
  </div>
  <p class="meta">Source: <code>.brain/index/graph.json</code> — run <code>brain-index rebuild</code> to refresh.</p>
  <table>
    <tr><th>Node Type</th><th>Count</th></tr>
    {node_type_rows}
  </table>
  <h3>Edges by Type</h3>
  <table>
    <tr><th>Edge Type</th><th>Count</th></tr>
    {edge_type_rows}
  </table>
</section>"""
    else:
        graph_section = """
<section id="knowledge-graph" class="diagnostic">
  <h2>Knowledge Graph</h2>
  <p class="meta">Graph data not available. Run <code>brain-index rebuild</code> to generate <code>.brain/index/graph.json</code>.</p>
</section>"""
    return graph_section


def release_blockers_of(index: Any, status: Any, summary: Any) -> list[str]:
    """Что мешает релизу. Список читают две секции: сами ворота и консоль оператора."""
    index_health = index_health_of(index)
    active_count = int(summary.get("active_count", 0))
    locks_stale = int(status["locks"].get("stale_count", 0))
    index_ok = index_health == "ok"
    release_blockers: list[str] = []
    if active_count:
        release_blockers.append(f"active tasks: {active_count}")
    if locks_stale:
        release_blockers.append(f"stale locks: {locks_stale}")
    if not index_ok:
        release_blockers.append(f"index health: {index_health}")
    return release_blockers


def release_label_of(blockers: list[str]) -> str:
    return "ready" if not blockers else "blocked"


def build_release_gates(index: Any, status: Any, summary: Any) -> str:
    release_blockers = release_blockers_of(index, status, summary)
    active_count = int(summary.get("active_count", 0))
    locks_stale = int(status["locks"].get("stale_count", 0))
    index_health = index_health_of(index)
    release_cls = "state-done" if not release_blockers else "state-blocked"
    release_label = release_label_of(release_blockers)
    blocker_rows = "".join(f"<li>{h(b)}</li>" for b in release_blockers)
    if not blocker_rows:
        blocker_rows = "<li><em>No lightweight blockers detected</em></li>"
    release_section = f"""
<section id="release-gates" class="diagnostic">
  <h2>Release Gates <span id="release-gates-status" class="badge {release_cls}">{h(release_label)}</span></h2>
  <p class="meta">Lightweight preview for the visual shell. Full release check remains <code>brain-release check</code>.</p>
  <div class="summary-row">
    <div class="card"><strong id="release-active-count">{h(active_count)}</strong><br>active tasks</div>
    <div class="card"><strong id="release-stale-locks">{h(locks_stale)}</strong><br>stale locks</div>
    <div class="card"><strong id="release-index-health">{h(index_health)}</strong><br>index health</div>
  </div>
  <h3>Current Blockers</h3>
  <ul id="release-blockers">{blocker_rows}</ul>
</section>"""
    return release_section


def build_obsidian_views(obsidian_views: Any) -> str:
    view_rows = ""
    for view_name, present in obsidian_views.items():
        view_cls = "" if present else "missing"
        view_rows += (
            f"<tr class='{view_cls}'>"
            f"<td class='mono'>{h(view_name)}</td>"
            f"<td>{'✓' if present else '—'}</td>"
            f"</tr>"
        )

    obsidian_section = f"""
<section id="obsidian-views" class="diagnostic">
  <h2>Obsidian Views</h2>
  <p>Location: <code>wiki/_views/</code> — run <code>brain-index rebuild --with-obsidian</code> to generate.</p>
  <table>
    <tr><th>View</th><th>Present</th></tr>
    {view_rows}
  </table>
</section>"""
    return obsidian_section


def build_token_economy(tokens: Any) -> str:
    token_agg = tokens.get("aggregate", {})
    token_rows = ""
    for item in tokens.get("recent", []):
        token_rows += (
            f"<tr>"
            f"<td class='small'>{h(item.get('ts',''))}</td>"
            f"<td>{h(item.get('kind',''))}</td>"
            f"<td>{h(item.get('provider',''))}</td>"
            f"<td>{h(item.get('role',''))}</td>"
            f"<td class='mono small'>{h(item.get('session',''))}</td>"
            f"<td>{h(item.get('raw_tokens_est',0))}</td>"
            f"<td>{h(item.get('compact_tokens_est',0))}</td>"
            f"<td>{h(item.get('savings_percent',0))}%</td>"
            f"<td class='mono small'>{h(item.get('raw_artifact',''))}</td>"
            f"</tr>"
        )
    if not token_rows:
        token_rows = "<tr><td colspan='9'><em>No compacted commands yet. Run brain-compact to populate this feed.</em></td></tr>"
    token_paths = tokens.get("paths") or [tokens.get("path", "$BRAIN/.brain/token-metrics.jsonl")]
    token_source = ", ".join(str(p) for p in token_paths if p)
    token_state = "live" if tokens.get("available") else "waiting for first compacted command"
    token_section = f"""
<section id="token-metrics">
  <h2>Token Economy</h2>
  <div class="summary-row">
    <div class="card"><strong id="token-commands">{h(token_agg.get('commands',0))}</strong><br>commands</div>
    <div class="card"><strong id="token-raw-tokens">{h(token_agg.get('raw_tokens_est',0))}</strong><br>raw tokens</div>
    <div class="card"><strong id="token-compact-tokens">{h(token_agg.get('compact_tokens_est',0))}</strong><br>compact tokens</div>
    <div class="card"><strong id="token-savings">{h(token_agg.get('savings_percent',0))}%</strong><br>savings</div>
  </div>
  <p class="meta">Status: <span id="token-status">{h(token_state)}</span> · Source: <code id="token-source">{h(token_source)}</code></p>
  <table>
    <tr><th>Timestamp</th><th>Kind</th><th>Provider</th><th>Role</th><th>Session</th><th>Raw</th><th>Compact</th><th>Savings</th><th>Raw Artifact</th></tr>
    {token_rows}
  </table>
</section>"""
    return token_section


def build_learning(status: Any) -> str:
    learning = status.get("learning", {})
    if learning.get("available"):
        counts = learning.get("counts", {})
        inc_rows = ""
        for inc in learning.get("recent_incidents", []):
            inc_rows += (
                f"<tr>"
                f"<td class='mono small'>{h(inc.get('id',''))}</td>"
                f"<td>{h(inc.get('source',''))}</td>"
                f"<td>{h(inc.get('severity',''))}</td>"
                f"<td class='mono small'>{h(inc.get('task_id',''))}</td>"
                f"<td class='small'>{h(inc.get('created',''))}</td>"
                f"</tr>"
            )
        if not inc_rows:
            inc_rows = "<tr><td colspan='5'><em>No incidents yet</em></td></tr>"
        lesson_rows = ""
        for lesson in learning.get("recent_lessons", []):
            status_name = lesson.get("status", "")
            status_cls = {
                "active": "state-done",
                "approved": "state-progress",
                "pending": "state-progress",
                "deprecated": "",
                "rejected": "state-blocked",
            }.get(status_name, "")
            roles = lesson.get("roles", [])
            if isinstance(roles, list):
                roles = ", ".join(roles)
            injectable = "yes" if lesson.get("injectable") else "no"
            lesson_rows += (
                f"<tr>"
                f"<td class='mono small'>{h(lesson.get('id',''))}</td>"
                f"<td><span class='badge {h(status_cls)}'>{h(status_name)}</span></td>"
                f"<td>{h(roles)}</td>"
                f"<td>{h(lesson.get('severity',''))}</td>"
                f"<td class='mono small'>{h(lesson.get('source',''))}</td>"
                f"<td>{h(lesson.get('confidence',''))}</td>"
                f"<td>{h(lesson.get('context_tokens_est',0))}</td>"
                f"<td>{h(injectable)}</td>"
                f"</tr>"
            )
        if not lesson_rows:
            lesson_rows = "<tr><td colspan='8'><em>No lessons yet</em></td></tr>"
        policy = learning.get("injection_policy", {})
        learning_section = f"""
<section id="learning" class="diagnostic">
  <h2>Learning Loop</h2>
  <div class="summary-row">
    <div class="card"><strong>{h(counts.get('incidents',0))}</strong><br>incidents</div>
    <div class="card"><strong>{h(counts.get('pending',0))}</strong><br>pending</div>
    <div class="card"><strong>{h(counts.get('approved',0))}</strong><br>approved</div>
    <div class="card"><strong>{h(counts.get('active',0))}</strong><br>active</div>
    <div class="card"><strong>{h(counts.get('deprecated',0))}</strong><br>deprecated</div>
  </div>
  <h3>Recent Incidents (no evidence)</h3>
  <table>
    <tr><th>ID</th><th>Source</th><th>Severity</th><th>Task</th><th>Created</th></tr>
    {inc_rows}
  </table>
  <h3>Lesson Review Queue</h3>
  <table>
    <tr><th>ID</th><th>Status</th><th>Roles</th><th>Severity</th><th>Source</th><th>Confidence</th><th>Context Tokens</th><th>Injectable</th></tr>
    {lesson_rows}
  </table>
  <p class="meta">Injection policy: active rule required={h(policy.get('active_rule_required', True))};
  pending injected={h(policy.get('pending_injected', False))}; max lessons={h(policy.get('max_lessons', 5))};
  max tokens={h(policy.get('max_tokens', 800))}.</p>
  <p class="meta">Full evidence: <code>$BRAIN_PATH/learning/incidents/</code> — not shown here.</p>
</section>"""
    else:
        learning_section = """
<section id="learning" class="diagnostic">
  <h2>Learning Loop</h2>
  <p class="meta">No learning data found. Run <code>brain-learn capture</code> to start.</p>
</section>"""
    return learning_section


def build_audit_log(audit_entries: Any, task_filter: Any) -> str:
    audit_rows = ""
    for entry in audit_entries:
        op_cls = (
            "state-done" if entry["op"] in ("task-done", "council-synth")
            else "state-in-progress" if entry["op"] in ("task-start", "council-start")
            else ""
        )
        audit_rows += (
            f"<tr>"
            f"<td class='mono small'>{h(entry['ts'])}</td>"
            f"<td><span class='badge {h(op_cls)}'>{h(entry['op'])}</span></td>"
            f"<td class='mono'>{h(entry['task'])}</td>"
            f"<td class='small'>{h(entry['agent'])}</td>"
            f"<td class='small'>{h(entry['extra'])}</td>"
            f"</tr>"
        )
    if not audit_rows:
        audit_rows = "<tr><td colspan='5'><em>No log entries</em></td></tr>"
    filter_note = f"<p>Filter: <code>{h(task_filter)}</code></p>" if task_filter else ""
    audit_section = f"""
<section id="audit-log" class="diagnostic">
  <h2>Audit Log <span class='badge'>{h(len(audit_entries))} recent</span></h2>
  <p>Source: <code>wiki/log.md</code> — last 20 write actions{', filtered' if task_filter else ''}</p>
  {filter_note}
  <table>
    <tr><th>Timestamp</th><th>Operation</th><th>Task ID</th><th>Agent</th><th>Extra</th></tr>
    {audit_rows}
  </table>
</section>"""
    return audit_section
