"""t-2026-08-21-validate-cycle-corrective: упавший вывод сохраняется в момент отказа.

Цикл, заведя corrective-задачу с приёмкой «diagnosed and fixed», обязан оставить
записанный след того, что именно упало, — иначе закрывающий задачу вынужден
реконструировать причину по памяти/коммитам, которых уже может не быть.
Контракт (как у model-fleet): stdout/stderr упавшего валидатора ложится в отчёт
под wiki/, corrective ссылается на него через `ref:` и упоминает в приёмке.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from brain_app.cycles import provider_probe, validate


def _make_brain(tmp_path: Path) -> Path:
    brain = tmp_path / "brain"
    (brain / "tasks").mkdir(parents=True)
    (brain / "tasks" / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    (brain / "tasks" / "done.md").write_text("", encoding="utf-8")
    (brain / "wiki").mkdir(parents=True)
    return brain


# ── validate ────────────────────────────────────────────────────────────────

def test_validate_writes_failure_report_with_output(tmp_path):
    brain = _make_brain(tmp_path)
    ts = dt.datetime(2026, 8, 21, 12, 0, 0)
    result = {
        "command": "brain-validate",
        "exit_code": 1,
        "stdout": "ERROR: invalid task ref 't-x' in wiki/dangling.md",
        "stderr": "fatal: something went wrong",
    }
    path = validate.write_failure_report(brain, ts, result)

    assert path.name == "validate-cycle-2026-08-21-120000Z.md"
    text = path.read_text(encoding="utf-8")
    assert "ERROR: invalid task ref 't-x'" in text
    assert "fatal: something went wrong" in text
    assert "validate-cycle:failure" in text


def test_validate_corrective_carries_report_ref_and_acceptance(tmp_path):
    brain = _make_brain(tmp_path)
    report_rel = "wiki/validate-cycle-2026-08-21-120000Z.md"
    created, message = validate.append_corrective_task(brain, report_rel)
    assert created is True
    active = (brain / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "source: validate-cycle:failure" in active
    assert f"      ref: {report_rel}" in active
    # приёмка называет адрес записанного следа — «diagnosed» опирается на записанное
    acceptance = next(ln for ln in active.splitlines() if ln.strip().startswith("acceptance:"))
    assert report_rel in acceptance
    assert "not on memory" in acceptance or "memory" in acceptance


# ── provider_probe ──────────────────────────────────────────────────────────

def test_provider_probe_writes_failure_report_with_down(tmp_path):
    brain = _make_brain(tmp_path)
    ts = dt.datetime(2026, 8, 21, 12, 0, 0)
    down = {"developer": {"key": "claude/opus", "status": "error"}}
    path = provider_probe.write_failure_report(brain, ts, down)

    assert path.name == "provider-probe-2026-08-21-120000Z.md"
    text = path.read_text(encoding="utf-8")
    assert "developer" in text
    assert "claude/opus" in text
    assert "provider-probe:down" in text


def test_provider_probe_corrective_carries_report_ref(tmp_path):
    brain = _make_brain(tmp_path)
    down = {"developer": {"key": "claude/opus", "status": "error"}}
    report_rel = "wiki/provider-probe-2026-08-21-120000Z.md"
    created, message = provider_probe.append_corrective_task(brain, down, report_rel)
    assert created is True
    active = (brain / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "source: provider-probe:down" in active
    assert f"      ref: {report_rel}" in active
    assert report_rel in active


# ── отчёт — единственный источник диагноза, без старых записей он пересоздаётся ──

def test_validate_report_is_rewritten_even_if_duplicate_corrective_skipped(tmp_path):
    """Задача-дубликат пропускается, но свежий отчёт пишется на каждый провал.

    Это важно: даже когда corrective уже висит в очереди, новый вывод обязан
    осесть в новом отчёте — иначе закрытие первой задачи увидит только первый
    сбой, а не последний.
    """
    brain = _make_brain(tmp_path)
    ts = dt.datetime(2026, 8, 21, 12, 0, 0)
    result = {"command": "brain-validate", "exit_code": 1, "stdout": "boom 1", "stderr": ""}
    validate.write_failure_report(brain, ts, result)
    validate.append_corrective_task(brain, "wiki/validate-cycle-2026-08-21-120000Z.md")

    ts2 = dt.datetime(2026, 8, 22, 12, 0, 0)
    result2 = {"command": "brain-validate", "exit_code": 1, "stdout": "boom 2", "stderr": ""}
    path2 = validate.write_failure_report(brain, ts2, result2)
    created, _ = validate.append_corrective_task(brain, str(path2.relative_to(brain)))
    assert created is False  # дубликат — задачи не множатся
    assert path2.exists()
    assert "boom 2" in path2.read_text(encoding="utf-8")
