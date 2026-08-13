"""Секция расписаний: cron, таймеры systemd и очередь at."""

from __future__ import annotations

from typing import Any

from brain_dashboard.schedule import UNSCHEDULED_LABEL

from .utils import h


def _render_scheduled_work(scheduled: dict[str, Any]) -> str:
    summary = scheduled.get("summary") or {}

    def status_badge(block: dict[str, Any]) -> str:
        status = str(block.get("status") or "unknown")
        cls = "state-done" if status == "ok" else "state-blocked"
        return f"<span class='badge {h(cls)}'>{h(status)}</span>"

    rows = ""
    cron = scheduled.get("cron") or {}
    cron_items = cron.get("items") or []
    if cron_items:
        for item in cron_items:
            rows += (
                f"<tr><td>cron</td><td>{status_badge(cron)}</td>"
                f"<td class='mono small'>{h(item.get('schedule', ''))}</td>"
                f"<td>{h(item.get('command', ''))}</td></tr>"
            )
    else:
        rows += (
            f"<tr><td>cron</td><td>{status_badge(cron)}</td>"
            f"<td class='mono small'>—</td><td>{h(cron.get('error') or 'no entries')}</td></tr>"
        )

    timers = scheduled.get("systemd_timers") or {}
    timer_items = timers.get("items") or []
    scheduled_timers = [item for item in timer_items if item.get("next") != UNSCHEDULED_LABEL]
    unscheduled_timers = [item for item in timer_items if item.get("next") == UNSCHEDULED_LABEL]
    if scheduled_timers:
        for item in scheduled_timers:
            detail = f"{item.get('unit', '')} -> {item.get('activates', '')}".strip()
            rows += (
                f"<tr><td>systemd timer</td><td>{status_badge(timers)}</td>"
                f"<td class='mono small'>{h(item.get('next', ''))}</td>"
                f"<td>{h(detail)}</td></tr>"
            )
    elif not unscheduled_timers:
        rows += (
            f"<tr><td>systemd timer</td><td>{status_badge(timers)}</td>"
            f"<td class='mono small'>—</td><td>{h(timers.get('error') or 'no timers')}</td></tr>"
        )

    at_block = scheduled.get("at") or {}
    at_items = at_block.get("items") or []
    if at_items:
        for item in at_items:
            rows += (
                f"<tr><td>at</td><td>{status_badge(at_block)}</td>"
                f"<td class='mono small'>{h(item.get('id', ''))}</td>"
                f"<td>{h(item.get('raw', ''))}</td></tr>"
            )
    else:
        rows += (
            f"<tr><td>at</td><td>{status_badge(at_block)}</td>"
            f"<td class='mono small'>—</td><td>{h(at_block.get('error') or 'no jobs')}</td></tr>"
        )

    unscheduled_block = ""
    if unscheduled_timers:
        unscheduled_rows = ""
        for item in unscheduled_timers:
            detail = f"{item.get('unit', '')} -> {item.get('activates', '')}".strip()
            unscheduled_rows += (
                f"<tr><td>systemd timer</td>"
                f"<td><span class='badge state-open'>{h(UNSCHEDULED_LABEL)}</span></td>"
                f"<td class='mono small'>{h(UNSCHEDULED_LABEL)}</td>"
                f"<td>{h(detail)}</td></tr>"
            )
        unscheduled_block = f"""
  <div id="unscheduled-timers">
    <h3>{h(UNSCHEDULED_LABEL)}</h3>
    <table>
      <tr><th>Source</th><th>Status</th><th>Schedule / Next</th><th>Command / Unit</th></tr>
      {unscheduled_rows}
    </table>
  </div>"""

    return f"""
<section id="scheduled-work">
  <h2>Scheduled Work</h2>
  <p class="meta">Read-only check for work outside the Brain queue: user crontab, user systemd timers, and at jobs.</p>
  <div class="summary-row">
    <div class="card"><strong>{h(summary.get('cron', 0))}</strong><br>cron</div>
    <div class="card"><strong>{h(summary.get('systemd_timers', 0))}</strong><br>timers</div>
    <div class="card"><strong>{h(summary.get('at', 0))}</strong><br>at jobs</div>
  </div>
  <table>
    <tr><th>Source</th><th>Status</th><th>Schedule / Next</th><th>Command / Unit</th></tr>
    {rows}
  </table>
  {unscheduled_block}
</section>"""
