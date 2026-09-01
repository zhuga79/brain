"""t-2026-08-10-core-cycles-runner: общее ядро периодических команд.

Проверяем ровно те свойства, ради которых шесть копий сведены в одну: юнит
собирается по правилам systemd, corrective-задача не размножается, обвязка
разбирает аргументы одинаково для всех циклов.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from brain_core import clock
from brain_app.cycles import (
    corrective,
    index_refresh,
    provider_probe,
    queue,
    review,
    runner,
    systemd,
    sync,
    validate,
)

REPO = Path(__file__).resolve().parent.parent.parent


# ── systemd ──────────────────────────────────────────────────────────────────

def make_spec(**overrides) -> systemd.UnitSpec:
    base = dict(
        name="brain-demo-cycle",
        service_description="Demo",
        timer_description="Demo daily",
        command=Path("/usr/bin/brain-demo-cycle"),
        exec_args=["--apply"],
        timer_options=[("OnCalendar", "daily")],
    )
    base.update(overrides)
    return systemd.UnitSpec(**base)


@pytest.mark.parametrize("name", ["evil", "../brain-x", "brain x", "systemd-brain"])
def test_unit_name_rejected(name):
    """Имя уходит и в путь файла, и в аргумент systemctl."""
    with pytest.raises(systemd.UnitNameError):
        make_spec(name=name)


def test_environment_assignment_is_quoted_whole():
    """Без кавычек systemd обрезает значение по первому пробелу."""
    service = systemd.render_service(make_spec(environment=[("BRAIN_PATH", "/home/u/my brain")]))
    assert 'Environment="BRAIN_PATH=/home/u/my brain"' in service


def test_percent_is_escaped_everywhere():
    """`%` — спецификатор systemd, и кавычки от него не защищают."""
    service = systemd.render_service(make_spec(
        command=Path("/opt/100%/brain-demo-cycle"),
        environment=[("BRAIN_PATH", "/data/50%")],
    ))
    assert "100%%" in service and "50%%" in service
    assert "100%/" not in service


def test_plain_arguments_stay_unquoted():
    service = systemd.render_service(make_spec())
    assert "ExecStart=/usr/bin/brain-demo-cycle --apply" in service


def test_path_with_space_is_quoted():
    service = systemd.render_service(make_spec(exec_args=["--brain", "/home/u/my brain"]))
    assert '"--brain"' not in service  # флаг не требует кавычек
    assert '"/home/u/my brain"' in service


def test_timer_names_its_service_explicitly():
    """При --unit-name имена таймера и сервиса расходятся, и связь нужна явная."""
    timer = systemd.render_timer(make_spec(name="brain-sync-kvashnino"))
    assert "Unit=brain-sync-kvashnino.service" in timer
    assert "WantedBy=timers.target" in timer


def test_unit_options_land_in_unit_section():
    service = systemd.render_service(make_spec(unit_options=[("After", "network-online.target")]))
    head = service.split("[Service]", 1)[0]
    assert "After=network-online.target" in head


def test_systemctl_scope_never_passes_empty_argument(monkeypatch):
    """Прежние копии под root подставляли пустую строку вместо области."""
    monkeypatch.setattr(systemd.os, "geteuid", lambda: 0)
    assert systemd.systemctl_args("daemon-reload") == ["systemctl", "daemon-reload"]
    monkeypatch.setattr(systemd.os, "geteuid", lambda: 1000)
    assert systemd.systemctl_args("daemon-reload") == ["systemctl", "--user", "daemon-reload"]


def test_install_writes_both_units(tmp_path):
    payload = systemd.install(make_spec(), unit_dir=tmp_path / "units", enable=False)
    assert Path(payload["service"]).exists() and Path(payload["timer"]).exists()
    assert payload["enabled"] is False and payload["ok"] is True


def _unit_section_lines(service: str) -> list[str]:
    return [line for line in service.split("[Service]", 1)[0].splitlines() if line]


def _rendered_cycle_service(module, extra: dict | None = None) -> str:
    args = argparse.Namespace(brain="/tmp/brain", **(extra or {}))
    return systemd.render_service(module.unit(args))


# [Unit] сервиса — построчно как в оригинальных установщиках (b240509^).
# Wants=<таймер> был у трёх циклов и потерялся при сведении в общий генератор.
ORIGINAL_SERVICE_UNIT = {
    "validate": [
        "[Unit]",
        "Description=Run brain-validate cycle",
        "Wants=brain-validate-cycle.timer",
    ],
    "index_refresh": [
        "[Unit]",
        "Description=Run brain-index-refresh cycle",
        "Wants=brain-index-refresh.timer",
    ],
    "provider_probe": [
        "[Unit]",
        "Description=Probe brain providers and create corrective task",
        "Wants=brain-provider-probe.timer",
    ],
    "queue": [
        "[Unit]",
        "Description=Brain daily queue-cycle launch proposal builder",
    ],
    "review": [
        "[Unit]",
        "Description=Brain recurring reviewer cycle",
    ],
    "sync": [
        "[Unit]",
        "Description=Synchronize Brain durable state with LAN git remote",
        "After=network-online.target",
        "Wants=network-online.target",
    ],
}

CYCLE_UNIT_ARGS = {
    "validate": (validate, {}),
    "index_refresh": (index_refresh, {}),
    "provider_probe": (provider_probe, {}),
    "queue": (queue, {"agent": "codex-gpt5-queue-cycle"}),
    "review": (review, {"role": "reviewer", "agent": "codex-gpt5-review-cycle"}),
    "sync": (
        sync,
        {
            "repo": None,
            "unit_name": "brain-sync",
            "interval": "5min",
            "rebuild_index": True,
        },
    ),
}


@pytest.mark.parametrize("cycle", list(ORIGINAL_SERVICE_UNIT))
def test_cycle_unit_section_matches_original(cycle):
    """Секция [Unit] каждого из шести циклов совпадает с оригиналом построчно."""
    module, extra = CYCLE_UNIT_ARGS[cycle]
    assert _unit_section_lines(_rendered_cycle_service(module, extra)) == ORIGINAL_SERVICE_UNIT[cycle]


@pytest.mark.parametrize(
    "cycle, timer",
    [
        ("validate", "brain-validate-cycle.timer"),
        ("index_refresh", "brain-index-refresh.timer"),
        ("provider_probe", "brain-provider-probe.timer"),
    ],
)
def test_wants_timer_present_in_validate_index_refresh_provider_probe(cycle, timer):
    """Ручной старт сервиса должен подтянуть таймер, как до сведения копий."""
    module, extra = CYCLE_UNIT_ARGS[cycle]
    head = _rendered_cycle_service(module, extra).split("[Service]", 1)[0]
    assert f"Wants={timer}" in head


# ── t-2026-08-16-operator-timers-dead-user-serv ─────────────────────────────
#
# systemd user-менеджер стартует сервисы с минимальным PATH и без .pth,
# который `setup-brain-v2.sh` кладёт в user site-packages интерактивного
# python3. Все шесть циклов упали `ModuleNotFoundError: No module named
# 'brain_app'` под systemd, оставаясь `active` по `systemctl list-timers`.

@pytest.mark.parametrize("cycle", list(CYCLE_UNIT_ARGS))
def test_every_cycle_unit_carries_pythonpath(cycle, monkeypatch):
    """Все шесть юнитов несут PYTHONPATH на runtime/lib системного чекаута."""
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(REPO))
    module, extra = CYCLE_UNIT_ARGS[cycle]
    args = argparse.Namespace(brain="/tmp/brain", **extra)
    env = dict(module.unit(args).environment)
    assert env.get("PYTHONPATH") == str(REPO / "runtime" / "lib")
    assert env.get("BRAIN_PATH") == "/tmp/brain"


def test_service_environment_follows_split_root(monkeypatch, tmp_path):
    """Данные и система расходятся (как на машине оператора) — PYTHONPATH
    указывает на систему, а не на дерево данных."""
    monkeypatch.setenv("BRAIN_SYSTEM_PATH", str(REPO))
    data_root = tmp_path / "data-only-brain"
    env = dict(runner.service_environment(data_root))
    assert env["BRAIN_PATH"] == str(data_root)
    assert env["PYTHONPATH"] == str(REPO / "runtime" / "lib")


def test_service_environment_falls_back_to_brain_without_split_root(monkeypatch, tmp_path):
    """Без BRAIN_SYSTEM_PATH система = дерево данных, как до разделения корней."""
    monkeypatch.delenv("BRAIN_SYSTEM_PATH", raising=False)
    brain = tmp_path / "brain"
    env = dict(runner.service_environment(brain))
    assert env["PYTHONPATH"] == str(brain / "runtime" / "lib")


def test_core_import_fails_under_a_pth_less_interpreter_without_pythonpath(tmp_path):
    """Регресс-тест: интерпретатор без .pth не видит brain_app без PYTHONPATH.

    Это ровно та картина, что двое суток показывал журнал systemd: `env
    python3` резолвится в интерпретатор, куда `brain-runtime.pth` никогда не
    ставился (systemd-пользовательский менеджер даёт минимальный PATH и не
    читает login-shell). HOME подменён на пустой каталог, поэтому даже если
    тест запускает интерактивный python3 с реальным .pth оператора, в этом
    прогоне .pth не находится — интерпретатор honестно «без .pth».
    """
    fake_home = tmp_path / "home-without-pth"
    fake_home.mkdir()
    bare_env = {"PATH": "/usr/bin:/bin", "HOME": str(fake_home)}

    broken = subprocess.run(
        [sys.executable, "-c", "import brain_app"],
        env=bare_env, capture_output=True, text=True,
    )
    assert broken.returncode != 0
    assert "ModuleNotFoundError" in broken.stderr
    assert "brain_app" in broken.stderr


def test_service_environment_pythonpath_recovers_the_same_interpreter(tmp_path):
    """Тот же интерпретатор из предыдущего теста — с PYTHONPATH из
    `runner.service_environment` — импортирует brain_app как обычно."""
    fake_home = tmp_path / "home-without-pth"
    fake_home.mkdir()
    bare_env = {"PATH": "/usr/bin:/bin", "HOME": str(fake_home)}

    env_vars = dict(runner.service_environment(REPO))
    fixed_env = dict(bare_env, PYTHONPATH=env_vars["PYTHONPATH"])

    fixed = subprocess.run(
        [sys.executable, "-c", "import brain_app; print('ok')"],
        env=fixed_env, capture_output=True, text=True,
    )
    assert fixed.returncode == 0, fixed.stderr
    assert fixed.stdout.strip() == "ok"


# ── corrective ───────────────────────────────────────────────────────────────

def make_brain(tmp_path: Path, active: str = "# Active Tasks\n", done: str = "") -> Path:
    brain = tmp_path / "brain"
    (brain / "tasks").mkdir(parents=True)
    (brain / "tasks" / "active.md").write_text(active, encoding="utf-8")
    (brain / "tasks" / "done.md").write_text(done, encoding="utf-8")
    return brain


ITEM = corrective.Corrective(title="Fix the thing", source="demo-cycle:failure", role="linter", priority="P1")


def _completed(delta: timedelta) -> str:
    return clock.utc_now(clock.now() - delta)


def _done(*, completed: str | None = None, task_id: str = "t-old") -> str:
    lines = [
        f"- [x] [P1] {task_id} — {ITEM.title}",
        f"      source: {ITEM.source}",
    ]
    if completed is not None:
        lines.append(f"      completed: {completed}")
    return "\n".join(lines) + "\n"


def test_corrective_appends_parsable_block(tmp_path):
    brain = make_brain(tmp_path)
    added = corrective.append(brain, [ITEM], day="2026-08-12")
    assert added == ["t-2026-08-12-fix-the-thing"]
    text = (brain / "tasks" / "active.md").read_text(encoding="utf-8")
    assert "- [ ] [P1] t-2026-08-12-fix-the-thing — Fix the thing" in text
    assert "      role: linter   mode: solo" in text
    assert "      source: demo-cycle:failure" in text


def test_corrective_is_deduped_by_source(tmp_path):
    brain = make_brain(tmp_path)
    corrective.append(brain, [ITEM], day="2026-08-12")
    assert corrective.append(brain, [ITEM], day="2026-08-13") == []


def test_corrective_sees_the_archive(tmp_path):
    """Свежий completed: в done.md — воскрешение сразу после закрытия невозможно.

    Прежние копии validate и provider-probe смотрели только active.md и
    воскрешали задачу на каждом прогоне после её закрытия.
    """
    brain = make_brain(tmp_path, done=_done(completed=_completed(timedelta(minutes=5))))
    assert corrective.append(brain, [ITEM], day="2026-08-12") == []
    assert corrective.already_queued(ITEM, "", _done(completed=_completed(timedelta(minutes=5))))


def test_corrective_recurs_after_silence_window(tmp_path):
    """Архивный хит старше 72ч — новый инцидент, новый id."""
    done = _done(completed=_completed(timedelta(hours=73)))
    brain = make_brain(tmp_path, done=done)
    assert corrective.already_queued(ITEM, "", done) is False
    assert corrective.append(brain, [ITEM], day="2026-08-12") == ["t-2026-08-12-fix-the-thing"]


def test_corrective_active_match_always_blocks(tmp_path):
    """Совпадение в active.md блокирует даже при протухшем архиве."""
    active = f"- [ ] [P1] t-live — {ITEM.title}\n      source: {ITEM.source}\n"
    done = _done(completed=_completed(timedelta(hours=80)))
    brain = make_brain(tmp_path, active=active, done=done)
    assert corrective.already_queued(ITEM, active, done)
    assert corrective.already_queued(ITEM, active, "")
    assert corrective.append(brain, [ITEM], day="2026-08-12") == []


def test_corrective_done_without_completed_does_not_mute(tmp_path):
    """Запись в done.md без completed: не глушит источник навсегда."""
    done = _done()
    brain = make_brain(tmp_path, done=done)
    assert corrective.already_queued(ITEM, "", done) is False
    assert corrective.append(brain, [ITEM], day="2026-08-12") == ["t-2026-08-12-fix-the-thing"]


def test_corrective_uses_newest_completed_in_archive(tmp_path):
    """Из совпавших блоков done.md берётся самый новый completed:."""
    done = _done(completed=_completed(timedelta(hours=80)), task_id="t-ancient")
    done += _done(completed=_completed(timedelta(minutes=5)), task_id="t-recent")
    brain = make_brain(tmp_path, done=done)
    assert corrective.already_queued(ITEM, "", done)
    assert corrective.append(brain, [ITEM], day="2026-08-12") == []


def test_done_silence_references_the_decision():
    assert corrective.DONE_SILENCE == timedelta(hours=72)
    assert "decision-corrective-recurrence" in inspect.getsource(corrective)


def test_explicit_slug_survives_a_reworded_title(tmp_path):
    brain = make_brain(tmp_path)
    item = corrective.Corrective(title="Anything at all", source="s:1", slug="validate-cycle-fix")
    assert corrective.append(brain, [item], day="2026-08-12") == ["t-2026-08-12-validate-cycle-fix"]


def test_batch_avoids_id_collision_inside_one_run(tmp_path):
    brain = make_brain(tmp_path)
    items = [
        corrective.Corrective(title="Same name", source="s:1"),
        corrective.Corrective(title="Same name!", source="s:2"),
    ]
    added = corrective.append(brain, items, day="2026-08-12")
    assert added == ["t-2026-08-12-same-name", "t-2026-08-12-same-name-2"]


def test_ref_line_is_optional(tmp_path):
    brain = make_brain(tmp_path)
    corrective.append(brain, [corrective.Corrective(title="No ref", source="s:1")], day="2026-08-12")
    assert "      ref:" not in (brain / "tasks" / "active.md").read_text(encoding="utf-8")


def test_empty_batch_touches_nothing(tmp_path):
    brain = make_brain(tmp_path)
    before = (brain / "tasks" / "active.md").read_text(encoding="utf-8")
    assert corrective.append(brain, []) == []
    assert (brain / "tasks" / "active.md").read_text(encoding="utf-8") == before


# ── runner ───────────────────────────────────────────────────────────────────

def demo_spec(**overrides) -> runner.CycleSpec:
    base = dict(
        name="brain-demo-cycle",
        description="Demo",
        run=lambda args: 0,
        unit=lambda args: make_spec(),
    )
    base.update(overrides)
    return runner.CycleSpec(**base)


def test_dry_run_is_the_default_mode():
    seen: dict[str, argparse.Namespace] = {}
    spec = demo_spec(run=lambda args: seen.setdefault("args", args) and 0 or 0)
    runner.dispatch(spec, [])
    assert seen["args"].dry_run is True and seen["args"].apply is False


def test_mode_can_be_made_mandatory():
    spec = demo_spec(mode_required=True)
    with pytest.raises(SystemExit):
        runner.dispatch(spec, [])


def test_sync_without_args_prints_help_and_does_not_start_dry_run(capsys, monkeypatch):
    """До b240509 вызов без режима печатал help и возвращал 2, а не уходил в dry-run."""
    monkeypatch.setattr(sync, "dry_run", lambda args: pytest.fail("dry-run must not start"))
    monkeypatch.setattr(sync, "apply_sync", lambda args: pytest.fail("apply must not start"))
    with pytest.raises(SystemExit) as exc:
        runner.dispatch(sync.SPEC, [])
    assert exc.value.code == 2
    printed = capsys.readouterr()
    text = f"{printed.out}\n{printed.err}"
    assert "usage:" in text
    assert "--dry-run" in text


def test_commit_journal_after_sync_commits_sync_audit_row(tmp_path):
    """t-2026-08-16-multi-user-federation-readines-s1: brain-federation sync
    appends node-attributed audit rows to wiki/log.md; the sync cycle must
    commit that journal dirt so the next apply is not blocked by
    dirty-worktree."""
    repo = tmp_path / "repo"
    (repo / "wiki").mkdir(parents=True)
    (repo / "tasks").mkdir(parents=True)
    (repo / "MEMORY.md").write_text("# Test Brain\n")
    (repo / "tasks" / "active.md").write_text("# Active\n")
    (repo / "wiki" / "log.md").write_text("# Log\n")
    (repo / ".gitignore").write_text(
        ".locks/\n.brain/\n.provider-health.json\nhandoff/ORCHESTRATOR_HANDOFF.md\nwiki/_views/\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "cycle@example.org"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Cycle"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)

    with (repo / "wiki" / "log.md").open("a", encoding="utf-8") as handle:
        handle.write("## [2026-08-30T00:00:00Z] federation-sync | /repo | node=n1 | status=ok\n")

    assert sync.commit_journal_after_sync(repo, already_committed=False) is True
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--", "wiki/log.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status == ""
    last = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert last == "chore: автозаписи журнала (brain-sync)"


def _cycle_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "wiki").mkdir(parents=True)
    (repo / "tasks").mkdir(parents=True)
    (repo / "MEMORY.md").write_text("# Test Brain\n")
    (repo / "tasks" / "active.md").write_text("# Active\n")
    (repo / "wiki" / "log.md").write_text("# Log\n")
    (repo / ".gitignore").write_text(
        ".locks/\n.brain/\n.provider-health.json\nhandoff/ORCHESTRATOR_HANDOFF.md\nwiki/_views/\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "cycle@example.org"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Cycle"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
    return repo


def test_apply_sync_passes_brain_and_commits_journal(tmp_path, monkeypatch, capsys):
    """Successful cycle path: --brain is forwarded and post-sync journal is committed."""
    repo = _cycle_repo(tmp_path)
    seen: dict[str, object] = {}

    def fake_command_run(cmd, *, cwd=None, timeout=300):
        seen["cmd"] = list(cmd)
        seen["cwd"] = cwd
        log = repo / "wiki" / "log.md"
        log.write_text(
            log.read_text(encoding="utf-8")
            + "## [2026-08-30T00:00:00Z] federation-sync | /repo |  | node=n1 | status=ok\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true, "status": "synced"}', stderr="")

    monkeypatch.setattr(sync, "command_run", fake_command_run)
    args = argparse.Namespace(
        brain=str(repo),
        repo=str(repo),
        timeout=30,
        json=True,
        apply=True,
        rebuild_index=False,
        dry_run=False,
    )
    assert sync.apply_sync(args) == 0
    expected_repo = str(repo.resolve())
    assert seen["cmd"] == [
        "brain-federation", "sync", "--repo", expected_repo,
        "--brain", expected_repo, "--json",
    ]
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--", "wiki/log.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert status == ""
    last = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert last == "chore: автозаписи журнала (brain-sync)"
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "synced"
    assert payload["journal_committed"] is True


def test_commit_journal_after_sync_leaves_unrelated_dirt(tmp_path):
    """If durable dirt beyond the journal exists, the audit row stays for a
    manual commit — nothing is force-committed."""
    repo = tmp_path / "repo"
    (repo / "wiki").mkdir(parents=True)
    (repo / "tasks").mkdir(parents=True)
    (repo / "wiki" / "log.md").write_text("# Log\n")
    (repo / "tasks" / "active.md").write_text("# Active\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "cycle@example.org"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Cycle"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)

    (repo / "tasks" / "active.md").write_text("# Active\n- [ ] [P1] t-x — New task\n")
    (repo / "wiki" / "log.md").write_text(
        "# Log\n## [2026-08-30T00:00:00Z] federation-sync | /repo | node=n1 | status=ok\n"
    )

    assert sync.commit_journal_after_sync(repo, already_committed=False) is False
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert "wiki/log.md" in status


@pytest.mark.parametrize(
    "module, required",
    [
        (validate, True),
        (index_refresh, True),
        (provider_probe, True),
        (queue, False),
        (review, False),
    ],
)
def test_other_cycles_keep_their_mode_policy(module, required):
    """Пять остальных циклов не меняют, обязателен режим или нет."""
    assert module.SPEC.mode_required is required


def test_install_subcommand_is_recognised_by_first_word(tmp_path):
    spec = demo_spec(run=lambda args: pytest.fail("run must not be called for install-systemd"))
    assert runner.dispatch(spec, ["install-systemd", "--unit-dir", str(tmp_path), "--no-enable"]) == 0
    assert (tmp_path / "brain-demo-cycle.timer").exists()


def test_bad_unit_name_exits_with_two(tmp_path, capsys):
    def bad_unit(args):
        raise systemd.UnitNameError("плохое имя")

    code = runner.dispatch(demo_spec(unit=bad_unit), ["install-systemd", "--unit-dir", str(tmp_path)])
    assert code == 2
    assert "плохое имя" in capsys.readouterr().err
