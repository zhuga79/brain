"""t-2026-08-10-client: заказчик и проект как поля машинной грамматики.

Заказчик — единица биллинга (по нему собираются часы и отчёты), проект —
единица организации работы. До этой задачи оба жили как соглашение: парсер их
не извлекал, дашборд доставал проект перебором сырых строк блока.
"""

import json

import pytest

from brain_app import queue
from brain_task_parser import format_block, parse_block

ACTIVE = """# Active

- [ ] [P1] t-garshin — Починить парсер очереди
      role: developer   mode: solo

- [ ] [P1] t-shurt — Ревью контракта CLI
      role: reviewer   mode: solo

- [ ] [P2] t-brain — Своя разработка
      role: developer   mode: solo
"""
DONE = "# Done\n"


def _write(tmp_path):
    """Корень Brain с очередью: фильтры читают её через brain_app.queue."""
    tasks = tmp_path / "tasks"
    tasks.mkdir(exist_ok=True)
    (tasks / "active.md").write_text(ACTIVE, encoding="utf-8")
    (tasks / "done.md").write_text(DONE, encoding="utf-8")
    return str(tmp_path)


# --- граница значения ---

class TestValueBoundary:
    def test_two_fields_on_one_line(self):
        """Разделитель полей в строке — два и более пробела, а не конец строки."""
        info = parse_block("- [ ] [P1] t-c — T\n      client: ООО Ромашка   project: Аренда-складов\n")
        assert info["client"] == "ООО Ромашка"
        assert info["project"] == "Аренда-складов"

    def test_single_spaces_stay_inside_the_value(self):
        info = parse_block("- [ ] [P1] t-c — T\n      client: ООО «Ромашка и партнёры»\n")
        assert info["client"] == "ООО «Ромашка и партнёры»"

    def test_acceptance_stops_before_ref(self):
        """Та же граница спасает acceptance от поглощения соседнего поля."""
        block = ("- [ ] [P1] t-a — T\n"
                 "      acceptance: тест проходит   ref: wiki/page.md\n")
        assert parse_block(block)["acceptance"] == "тест проходит"

    def test_longer_field_name_wins_over_prefix(self):
        """`depends_on` не должен разбираться как `deps`."""
        info = parse_block("- [ ] [P1] t-d — T\n      client: Заказчик   depends_on: [t-x]\n")
        assert info["client"] == "Заказчик"
        assert info["deps"] == ["t-x"]


# --- round-trip ---

def test_round_trip_keeps_both_fields():
    block = ("- [ ] [P1] t-rt — Заголовок\n"
             "      role: developer   mode: solo\n"
             "      client: ООО Ромашка\n      project: Аренда-складов\n")
    info = parse_block(block)
    again = parse_block(format_block(info) + "\n")
    assert again["client"] == info["client"] == "ООО Ромашка"
    assert again["project"] == info["project"] == "Аренда-складов"


def test_absent_fields_are_empty_not_missing():
    """Потребители подставляют значения в строку — отсутствие даётся пустой строкой."""
    info = parse_block("- [ ] [P1] t-n — T\n      role: developer\n")
    assert info["client"] == "" and info["project"] == ""


# --- фильтры CLI: клиентский контур корневой очереди снят ---

def test_list_without_filter_returns_everything(tmp_path, capsys):
    brain = _write(tmp_path)
    queue.main(["--brain", brain, "list", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert {t["id"] for t in out["tasks"]} == {"t-garshin", "t-shurt", "t-brain"}


def test_list_rejects_client_flag(tmp_path):
    """--client больше не фильтрует корневую очередь и не молчит."""
    brain = _write(tmp_path)
    with pytest.raises(SystemExit):
        queue.main(["--brain", brain, "list", "--client", "ООО Ромашка", "--json"])


def test_next_rejects_client_flag(tmp_path):
    brain = _write(tmp_path)
    with pytest.raises(SystemExit):
        queue.main(["--brain", brain, "next", "--client", "ООО Василёк", "--json"])


def test_filter_and_next_have_no_client_parameter():
    import inspect
    assert "client" not in inspect.signature(queue.filter_tasks).parameters
    assert "client" not in inspect.signature(queue.next_task).parameters


def test_brain_task_help_omits_client_flag():
    from pathlib import Path

    text = Path(__file__).resolve().parents[2] / "runtime" / "bin" / "brain-task"
    source = text.read_text(encoding="utf-8")
    start = source.index("cat <<'USAGE'")
    end = source.index("USAGE", start + len("cat <<'USAGE'"))
    assert "--client" not in source[start:end]


# --- валидатор ---

class TestValidator:
    def _brain(self, tmp_path, body):
        (tmp_path / "tasks").mkdir(exist_ok=True)
        p = tmp_path / "tasks" / "active.md"
        p.write_text(body, encoding="utf-8")
        return tmp_path, p

    def test_project_without_client_warns(self, tmp_path):
        from brain_wiki.validators import validate_task_client_fields

        brain, path = self._brain(tmp_path, "- [ ] [P1] t-x — T\n      project: Аренда-складов\n")
        issues = validate_task_client_fields(brain, path)
        assert len(issues) == 1
        assert issues[0].severity == "WARN"
        assert "t-x" in issues[0].message

    def test_both_fields_are_fine(self, tmp_path):
        from brain_wiki.validators import validate_task_client_fields

        brain, path = self._brain(
            tmp_path, "- [ ] [P1] t-y — T\n      client: ООО Ромашка   project: Аренда-складов\n")
        assert validate_task_client_fields(brain, path) == []

    def test_client_without_project_is_fine(self, tmp_path):
        """Заказчик без проекта — норма: биллинг есть, внутренней группировки нет."""
        from brain_wiki.validators import validate_task_client_fields

        brain, path = self._brain(tmp_path, "- [ ] [P1] t-z — T\n      client: ООО Василёк\n")
        assert validate_task_client_fields(brain, path) == []

    def test_missing_file_is_not_an_issue(self, tmp_path):
        from brain_wiki.validators import validate_task_client_fields

        assert validate_task_client_fields(tmp_path, tmp_path / "tasks" / "нет.md") == []


class TestQueueScope:
    """Корневая очередь несёт только разработку Brain."""

    def _brain(self, tmp_path, body):
        (tmp_path / "tasks").mkdir(exist_ok=True)
        p = tmp_path / "tasks" / "active.md"
        p.write_text(body, encoding="utf-8")
        return tmp_path, p

    def test_client_task_in_root_queue_is_an_error(self, tmp_path):
        from brain_wiki.validators import validate_queue_scope

        brain, path = self._brain(
            tmp_path,
            "- [ ] [P1] t-делo — Проверить договор\n"
            "      role: lawyer   mode: solo\n"
            "      client: ООО Ромашка   project: Аренда-складов\n",
        )
        issues = validate_queue_scope(brain, path)
        assert len(issues) == 1
        assert issues[0].severity == "ERROR"
        assert "t-делo" in issues[0].message
        assert "TASKS.md" in issues[0].message

    def test_system_task_passes(self, tmp_path):
        from brain_wiki.validators import validate_queue_scope

        brain, path = self._brain(
            tmp_path,
            "- [ ] [P1] t-core — Свести фасады очереди\n      role: developer   mode: solo\n",
        )
        assert validate_queue_scope(brain, path) == []


    def test_client_mentioned_in_prose_is_not_a_client_task(self, tmp_path):
        """Проза, упоминающая поле, полем не является.

        `brain_task_parser.parse_block` ищет `client:` где угодно в строке,
        поэтому задача, объясняющая правило, срабатывала на саму себя.
        """
        from brain_wiki.validators import validate_queue_scope

        brain, path = self._brain(
            tmp_path,
            "- [ ] [P1] t-core — Свернуть клиентский контур\n"
            "      role: developer   mode: solo\n"
            "      Дела вынесены в workspace'ы, `client:` в корневой очереди запрещён.\n"
            "      acceptance: фильтры сняты\n",
        )
        assert validate_queue_scope(brain, path) == []

    def test_missing_file_is_not_an_issue(self, tmp_path):
        from brain_wiki.validators import validate_queue_scope

        assert validate_queue_scope(tmp_path, tmp_path / "tasks" / "нет.md") == []
