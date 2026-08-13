"""Секции для оператора: консоль, лимиты передачи работы, поиск, страницы вики.

Отделены от диагностических: диагностика отвечает на вопрос «что со здоровьем
системы», а эти секции — рабочие поверхности, ими пользуются, а не смотрят.
"""

from __future__ import annotations

from typing import Any

from .utils import h


def build_operator_console(brain: Any, handoff: Any, operator: Any, providers: Any, release_blockers: Any, release_label: Any, tokens: Any) -> str:
    provider_items = providers.get("items", []) if isinstance(providers, dict) else []
    provider_unavailable = sum(
        1 for p in provider_items
        if str(p.get("status", "")).upper() not in ("OK", "AVAILABLE", "")
    )
    provider_total = len(provider_items)
    provider_state = "ok" if provider_unavailable == 0 else f"{provider_unavailable}/{provider_total} unavailable"
    token_state = "live" if tokens.get("available") else "waiting"
    handoff_state = handoff.get("reason") if handoff.get("exists") else "none"
    if operator.get("available"):
        op_prompt = operator.get("prompt") or ""
        op_log = operator.get("log") or ""
        operator_body = f"""
  <div class="summary-row">
    <div class="card"><strong class="mono">{h(operator.get('task') or '—')}</strong><br>task</div>
    <div class="card"><strong>{h(operator.get('role') or '—')}</strong><br>role</div>
    <div class="card"><strong>{h(operator.get('agent') or '—')}</strong><br>agent</div>
    <div class="card"><strong>{h(operator.get('updated') or '—')}</strong><br>updated</div>
  </div>
  <table>
    <tr><th>Surface</th><th>Status</th><th>Path / Value</th></tr>
    <tr><td>Prompt</td><td>{h('present' if operator.get('prompt_exists') else 'missing')}</td><td class="mono small">{h(op_prompt)}</td></tr>
    <tr><td>Log</td><td>{h(str(operator.get('log_size', 0)) + ' bytes' if operator.get('log_exists') else 'missing')}</td><td class="mono small">{h(op_log)}</td></tr>
    <tr><td>Release</td><td>{h(release_label)}</td><td>{h(', '.join(release_blockers) if release_blockers else 'no lightweight blockers')}</td></tr>
    <tr><td>Handoff</td><td>{h(handoff_state)}</td><td class="mono small">{h(handoff.get('path') or '')}</td></tr>
    <tr><td>Providers</td><td>{h(provider_state)}</td><td>{h(str(provider_total))} configured provider role entries</td></tr>
    <tr><td>Token economy</td><td>{h(token_state)}</td><td>{h(str((tokens.get('aggregate') or {}).get('commands', 0)))} compacted command(s)</td></tr>
  </table>
  <p class="meta">Use <code>brain-orchestrator console --dry-run</code> to inspect the next launch without side effects.</p>"""
    else:
        operator_body = f"""
  <p class="meta">No operator console run recorded yet.</p>
  <p>Run <code>brain-orchestrator console --dry-run</code> to create an inspectable plan.</p>
  <p>Manifest path: <code>{h(operator.get('path') or str(brain / '.brain' / 'orchestrator' / 'latest.json'))}</code></p>"""

    operator_section = f"""
<section id="operator-console">
  <h2>Operator Console</h2>
  {operator_body}
</section>"""
    return operator_section


def build_handoff_limits(brain: Any, handoff: Any) -> str:
    if handoff.get("exists"):
        command_rows = "".join(
            f"<li><code>{h(cmd)}</code></li>" for cmd in handoff.get("commands", [])
        ) or "<li><em>No continuation commands found</em></li>"
        handoff_body = f"""
  <div class="summary-row">
    <div class="card"><strong>{h(handoff.get('reason') or 'unknown')}</strong><br>reason</div>
    <div class="card"><strong>{h(handoff.get('to_role') or '—')}</strong><br>to role</div>
    <div class="card"><strong class="mono">{h(handoff.get('next_task') or '—')}</strong><br>next task</div>
  </div>
  <table>
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Generated</td><td>{h(handoff.get('generated') or '—')}</td></tr>
    <tr><td>From</td><td>{h(handoff.get('from_agent') or '—')}</td></tr>
    <tr><td>Current task</td><td class="mono">{h(handoff.get('task') or '—')}</td></tr>
    <tr><td>Path</td><td class="mono small">{h(handoff.get('path') or '')}</td></tr>
  </table>
  <h3>Continuation Commands</h3>
  <ul>{command_rows}</ul>
  <p class="meta">Raw trigger output excerpts are intentionally hidden.</p>"""
    else:
        handoff_body = f"""
  <p class="meta">No local orchestrator handoff artifact found.</p>
  <p>Expected path: <code>{h(str(brain / 'handoff' / 'ORCHESTRATOR_HANDOFF.md'))}</code></p>"""

    handoff_section = f"""
<section id="handoff-limits" class="diagnostic">
  <h2>Handoff & Limits</h2>
  {handoff_body}
</section>"""
    return handoff_section


def build_search() -> str:
    search_section = """
<section id="search">
  <h2>Search</h2>
  <div class="search-box">
    <input type="search" id="search-q" placeholder="Search the brain...">
    <select id="search-mode">
      <option value="hybrid">hybrid</option>
      <option value="bm25">bm25</option>
      <option value="vector">vector</option>
    </select>
    <button type="button" id="search-btn" title="Искать по базе знаний (wiki)">Поиск</button>
    <span id="search-progress" style="display:none; align-self: center;" class="small">Идёт поиск…</span>
  </div>
  <div id="search-results" class="small"></div>
</section>"""
    return search_section
