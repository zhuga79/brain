"""brain-dashboard section builders."""

from __future__ import annotations

from typing import Any

from .utils import h, _provider_badge

REASON_CLASS = {
    "limit-near": "state-progress",
    "limit-exhausted": "state-blocked",
    "rate-limit": "state-blocked",
    "context-bleed": "state-blocked",
    "manual": "",
    "fallback": "state-progress",
    "done": "state-done",
}


def build_delta_section(delta: dict[str, Any]) -> str:
    if not delta.get("has_delta"):
        return ""

    def rows(items: list[str], cls: str = "") -> str:
        return "".join(f"<li class='{cls} mono'>{h(i)}</li>" for i in items) if items else "<li><em>none</em></li>"

    completed = delta["tasks_completed"]
    added = delta["tasks_added"]
    removed = delta["tasks_removed"]
    changed = delta["tasks_state_changed"]
    locks_acq = delta["locks_acquired"]
    locks_rel = delta["locks_released"]
    councils = delta["councils_new"]
    total = len(completed) + len(added) + len(removed) + len(changed) + len(locks_acq) + len(locks_rel) + len(councils)

    badge = f"<span class='badge state-progress'>{total} change(s)</span>" if total else "<span class='badge state-done'>no changes</span>"

    return f"""
<section id="delta">
  <h2>Changes since last snapshot {badge}</h2>
  <p class="small">Since: {h(delta['since'])}</p>
  <table>
    <tr><th>Category</th><th>Items</th></tr>
    <tr><td>Tasks completed</td><td><ul>{rows(completed, 'state-done')}</ul></td></tr>
    <tr><td>Tasks added</td><td><ul>{rows(added, 'state-open')}</ul></td></tr>
    <tr><td>Tasks removed (other)</td><td><ul>{rows(removed)}</ul></td></tr>
    <tr><td>State changes</td><td><ul>{rows(changed)}</ul></td></tr>
    <tr><td>Locks acquired</td><td><ul>{rows(locks_acq)}</ul></td></tr>
    <tr><td>Locks released</td><td><ul>{rows(locks_rel)}</ul></td></tr>
    <tr><td>New councils</td><td><ul>{rows(councils)}</ul></td></tr>
  </table>
</section>"""


def build_handoff_journal_section(handoffs: list[dict[str, Any]]) -> str:
    if not handoffs:
        return '<section id="handoff-journal" class="diagnostic"><h2>Recent Handoffs</h2><p><em>No handoffs recorded</em></p></section>'

    rows = ""
    for item in handoffs:
        art = item.get("artifact", {})
        reason = art.get("reason", "unknown")
        cls = REASON_CLASS.get(reason, "")

        rows += (
            f"<tr>"
            f"<td class='small'>{h(art.get('generated', '—'))}</td>"
            f"<td><span class='badge {h(cls)}'>{h(reason)}</span></td>"
            f"<td>{h(art.get('from_agent', '—'))}</td>"
            f"<td>{h(art.get('to_role', '—'))}</td>"
            f"<td class='mono small'>{h(art.get('task', '—'))}</td>"
            f"</tr>"
        )

    return f"""
<section id="handoff-journal" class="diagnostic">
  <h2>Recent Handoffs (Journal)</h2>
  <table>
    <tr><th>Timestamp</th><th>Reason</th><th>From Agent</th><th>To Role</th><th>Task</th></tr>
    {rows}
  </table>
</section>"""


def build_provider_cards_section(providers: dict[str, Any]) -> str:
    roles = providers.get("roles", {})
    if not roles:
        # Причина важнее факта: «не настроено» и «файл конфигурации не найден» —
        # разные состояния, и второе чинится одной командой.
        reason = providers.get("warning") or ""
        detail = f"<p class='meta'>{h(reason)}</p>" if reason else ""
        return ('<section id="providers" class="diagnostic"><h2>Provider Matrix</h2>'
                f'<p><em>No providers configured</em></p>{detail}</section>')

    cards = ""
    for role, info in sorted(roles.items()):
        preferred = info.get("preferred")
        fallbacks = info.get("fallback", [])
        unavailable = info.get("unavailable", [])

        # Rank-chain
        chain = []
        if preferred:
            chain.append(_provider_badge(preferred, "state-done"))
        for f in fallbacks:
            chain.append(_provider_badge(f, "state-progress"))
        for u in unavailable:
            chain.append(_provider_badge(u, "state-blocked"))

        cards += f"""
    <div class="card provider-card">
      <strong>{h(role)}</strong>
      <div class="chain">{' → '.join(chain)}</div>
    </div>"""

    return f"""
<section id="providers" class="diagnostic">
  <h2>Provider Matrix <button type="button" data-action="probe" class="small">Probe All</button></h2>
  <div class="summary-row cards-grid">
    {cards}
  </div>
  <p class="meta">Probes update <code>.provider-health.json</code> cache. Preferred provider is the highest-rank non-unavailable candidate.</p>
</section>"""


def build_activity_section(status: dict[str, Any], provider_by_role: dict[str, str]) -> str:
    active_tasks = status["tasks"]["active"]
    locks = {l["task_id"]: l for l in status["locks"]["items"]}
    in_progress = [t for t in active_tasks if t["state"] == "~"]

    if not in_progress:
        return '<section id="activity"><h2>Activity</h2><p><em>No active work</em></p></section>'

    rows = ""
    for t in in_progress:
        tid = t["id"]
        lock = locks.get(tid, {})
        agent = lock.get("owner", "—")
        age = lock.get("age_seconds")
        role = t.get("role") or "—"

        # Try to extract provider from agent-id (provider-model-id)
        provider = "—"
        if agent and "-" in agent:
            provider = agent.split("-")[0]
        if provider == "—" or provider == agent:
            # Fallback to provider_by_role
            provider = provider_by_role.get(role, "—")

        rows += (
            f"<tr>"
            f"<td class='mono'>{h(tid)}</td>"
            f"<td>{h(agent)}</td>"
            f"<td>{h(role)}</td>"
            f"<td>{h(provider)}</td>"
            f"<td>{h(f'{age}s' if age is not None else '—')}</td>"
            f"</tr>"
        )

    return f"""
<section id="activity">
  <h2>Activity</h2>
  <table>
    <tr><th>Task ID</th><th>Agent</th><th>Role</th><th>Provider</th><th>Last Refresh</th></tr>
    {rows}
  </table>
</section>"""


def build_wiki_pages_section(wiki: dict[str, Any]) -> str:
    """List wiki pages with Obsidian edit-deep-links and view-on-disk paths.

    Per Karpathy LLM-wiki principle: humans curate plain markdown via their
    own editor (Obsidian). Dashboard is read-only viewer; "edit" jumps to
    Obsidian via obsidian://open?vault=…&file=… URL scheme.

    Данные приходят из collect.knowledge.collect_wiki: сам список страниц,
    имя хранилища и префикс ссылки. ``link_prefix`` подменяет префикс ``wiki/``
    в пути файла, чтобы попасть в симлинк внутри хранилища Obsidian.
    """
    vault_name = wiki.get("vault", "brain")
    wiki_link_prefix = wiki.get("link_prefix", "brain-wiki")
    if not wiki.get("indexed"):
        return """
<section id="wiki-pages">
  <h2>Wiki Pages</h2>
  <p><em>No index found — run <code>brain-index rebuild</code>.</em></p>
</section>"""
    pages = wiki.get("pages") or []
    if not pages:
        return """
<section id="wiki-pages">
  <h2>Wiki Pages</h2>
  <p><em>No pages indexed yet — run <code>brain-index rebuild</code>.</em></p>
</section>"""

    from urllib.parse import quote
    rows = ""
    for p in sorted(pages, key=lambda x: x.get("slug", "")):
        slug = p.get("slug", "")
        title = p.get("title", "") or slug
        path = p.get("path", f"wiki/{slug}.md")
        curation = p.get("curation", "agent") or "agent"
        protected = p.get("protected", False)
        sources = len(p.get("sources", []) or [])
        last_rev = p.get("last_reviewed_at", "") or "—"

        obsidian_path = path.replace("wiki/", f"{wiki_link_prefix}/", 1) if path.startswith("wiki/") else path
        edit_url = f"obsidian://open?vault={quote(vault_name)}&file={quote(obsidian_path)}"

        badge = ""
        if curation == "human":
            badge = "<span class='badge state-done' title='Human-curated, protected from auto-overwrite'>human</span>"
        elif curation == "mixed":
            badge = "<span class='badge state-progress' title='Mixed curation'>mixed</span>"
        else:
            badge = "<span class='badge' title='Agent-curated'>agent</span>"

        if protected:
            badge += " <span class='badge state-blocked' title='protected: true'>locked</span>"

        rows += (
            "<tr>"
            f"<td class='mono'>{h(slug)}</td>"
            f"<td>{h(title)}</td>"
            f"<td>{badge}</td>"
            f"<td class='mono small'>{h(last_rev)}</td>"
            f"<td>{h(sources)}</td>"
            f"<td><a href=\"{h(edit_url)}\" title='Open in Obsidian'>✎ edit</a></td>"
            "</tr>"
        )

    return f"""
<section id="wiki-pages">
  <h2>Wiki Pages</h2>
  <p class="meta">Click <strong>✎ edit</strong> to open in Obsidian (vault: <code>{h(vault_name)}</code>).
     Files live on disk under <code>$BRAIN_PATH/wiki/</code>; edits are tracked by git.</p>
  <table>
    <tr><th>Slug</th><th>Title</th><th>Curation</th><th>Last reviewed</th><th>Sources</th><th>Edit</th></tr>
    {rows}
  </table>
</section>"""
