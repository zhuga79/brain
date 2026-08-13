"""t-2026-08-12-dash-schedule: разбор вывода cron/systemd/at на фикстурах.

Раньше эти парсеры жили внутри data.py рядом с subprocess.run, и проверить их
можно было только на машине с настроенными cron, systemd и at. Здесь разбор —
чистая функция от текста, а опрос подменяется.
"""

from __future__ import annotations

from brain_dashboard import schedule

CRONTAB = """\
# comment line
SHELL=/bin/bash
PATH=/usr/bin:/bin
MAILTO=""

0 3 * * * /usr/local/bin/backup.sh --full
*/15 * * * * echo hi
broken line
"""

TIMERS = """\
NEXT                        LEFT     LAST                        PASSED  UNIT                 ACTIVATES
Wed 2026-08-12 07:52:46 EEST 1min left Wed 2026-08-12 07:47:46 EEST 3min ago brain-sync.timer brain-sync.service
Thu 2026-08-13 00:18:05 EEST 16h left  Wed 2026-08-12 00:46:38 EEST 7h ago   brain-queue-cycle.timer brain-queue-cycle.service

7 timers listed.
"""

ATQ = """\
12\tWed Aug 12 09:00:00 2026 a user
13\tThu Aug 13 09:00:00 2026 a user
"""


def test_crontab_skips_comments_and_environment():
    items = schedule.parse_crontab(CRONTAB)
    assert [item["command"] for item in items] == ["/usr/local/bin/backup.sh --full", "echo hi"]
    assert items[0]["schedule"] == "0 3 * * *"


def test_crontab_ignores_lines_without_a_command():
    assert schedule.parse_crontab("* * * * *\n") == []


def test_timers_are_found_by_unit_name_not_by_column():
    """Колонки list-timers плавают между версиями; опора — имя юнита."""
    items = schedule.parse_systemd_timers(TIMERS)
    assert [item["unit"] for item in items] == ["brain-sync.timer", "brain-queue-cycle.timer"]
    assert items[0]["activates"] == "brain-sync.service"
    assert items[0]["next"].startswith("Wed 2026-08-12 07:52:46")


def test_timers_header_and_footer_are_not_jobs():
    assert schedule.parse_systemd_timers("NEXT LEFT LAST PASSED UNIT ACTIVATES\n0 timers listed.\n") == []


def test_timer_without_activates_is_still_reported():
    items = schedule.parse_systemd_timers("Wed 2026-08-12 07:52:46 EEST 1min left — — lonely.timer\n")
    assert items == [{"next": "Wed 2026-08-12 07:52:46 EEST 1min left — —", "unit": "lonely.timer", "activates": ""}]


NA_COMPACT = "n/a n/a n/a n/a lonely.timer lonely.service\n"
NA_PADDED = (
    "n/a                         n/a           n/a                         n/a          "
    "lonely.timer             lonely.service\n"
)


def test_unscheduled_timer_compact_line_is_kept_and_marked():
    """Компактная форма list-timers: NEXT=n/a без выравнивания колонок."""
    items = schedule.parse_systemd_timers(NA_COMPACT)
    assert items == [{
        "next": "не запланирован",
        "unit": "lonely.timer",
        "activates": "lonely.service",
    }]


def test_unscheduled_timer_padded_line_is_kept_and_marked():
    """Реальная форма systemctl: колонки выровнены пробелами, NEXT всё ещё n/a."""
    items = schedule.parse_systemd_timers(NA_PADDED)
    assert items == [{
        "next": "не запланирован",
        "unit": "lonely.timer",
        "activates": "lonely.service",
    }]


def test_timers_header_is_discarded_when_mixed_with_na_rows():
    text = (
        "NEXT                        LEFT     LAST                        PASSED  UNIT                 ACTIVATES\n"
        + NA_PADDED
        + "Wed 2026-08-12 07:52:46 EEST 1min left Wed 2026-08-12 07:47:46 EEST 3min ago brain-sync.timer brain-sync.service\n"
        + "7 timers listed.\n"
    )
    items = schedule.parse_systemd_timers(text)
    assert [item["unit"] for item in items] == ["lonely.timer", "brain-sync.timer"]
    assert items[0]["next"] == "не запланирован"
    assert items[1]["next"].startswith("Wed 2026-08-12")


def test_atq_keeps_the_whole_line():
    items = schedule.parse_atq(ATQ)
    assert [item["id"] for item in items] == ["12", "13"]
    assert "Wed Aug 12" in items[0]["raw"]


def test_collect_uses_the_injected_runner():
    outputs = {
        "crontab": CRONTAB,
        "systemctl": TIMERS,
        "atq": ATQ,
    }

    def fake(cmd: list[str]) -> dict[str, object]:
        return {"returncode": 0, "stdout": outputs[cmd[0]], "stderr": ""}

    result = schedule.collect(fake)
    assert result["summary"] == {"cron": 2, "systemd_timers": 2, "at": 2}
    assert result["cron"]["status"] == "ok"


def test_failed_probe_becomes_data_not_an_exception():
    """Отсутствие atq не должно ронять страницу — секция показывает ошибку."""
    def fake(cmd: list[str]) -> dict[str, object]:
        return {"returncode": 127, "stdout": "", "stderr": "command not found"}

    result = schedule.collect(fake)
    assert result["at"] == {"status": "error", "error": "command not found", "items": []}
    assert result["summary"]["at"] == 0


def test_probe_reports_a_missing_command():
    assert schedule.probe(["definitely-not-a-real-command-xyz"])["returncode"] == 127


def test_collect_counts_unscheduled_timers():
    def fake(cmd: list[str]) -> dict[str, object]:
        stdout = ""
        if cmd[0] == "systemctl":
            stdout = TIMERS.replace("7 timers listed.", NA_COMPACT + "7 timers listed.")
        return {"returncode": 0, "stdout": stdout, "stderr": ""}

    result = schedule.collect(fake)
    units = [item["unit"] for item in result["systemd_timers"]["items"]]
    assert "lonely.timer" in units
    assert result["summary"]["systemd_timers"] == 3
    lonely = next(item for item in result["systemd_timers"]["items"] if item["unit"] == "lonely.timer")
    assert lonely["next"] == "не запланирован"


def test_schedule_section_shows_unscheduled_timers_separately():
    from brain_dashboard.render.scheduled import _render_scheduled_work

    html = _render_scheduled_work({
        "summary": {"cron": 0, "systemd_timers": 2, "at": 0},
        "cron": {"status": "ok", "error": "", "items": []},
        "systemd_timers": {
            "status": "ok",
            "error": "",
            "items": [
                {
                    "next": "Wed 2026-08-12 07:52:46 EEST 1min left",
                    "unit": "brain-sync.timer",
                    "activates": "brain-sync.service",
                },
                {
                    "next": "не запланирован",
                    "unit": "lonely.timer",
                    "activates": "lonely.service",
                },
            ],
        },
        "at": {"status": "ok", "error": "", "items": []},
    })
    scheduled_start = html.index("brain-sync.timer")
    unscheduled_mark = html.index("не запланирован")
    unscheduled_unit = html.index("lonely.timer")
    assert "id='unscheduled-timers'" in html or 'id="unscheduled-timers"' in html
    assert unscheduled_mark > html.index("unscheduled-timers")
    assert unscheduled_unit > html.index("unscheduled-timers")
    assert scheduled_start < html.index("unscheduled-timers")
