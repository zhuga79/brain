"""Грамматика блока задачи: round-trip и единственность источника.

Раньше форма блока была записана в нескольких местах по-разному, и задача,
записанная вне читательской грамматики, молча выпадала из очереди, дашборда,
индекса и MCP. Эти тесты закрепляют, что форма одна.
"""

import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "runtime" / "lib"))

from brain_core import grammar  # noqa: E402

STATES = [" ", "~", "x", "!"]
PRIOS = [None, "P0", "P1", "P2", "P3"]
TITLES = [
    "Короткий заголовок",
    "Заголовок с — тире и «кавычками»",
    "Title with [brackets] and (parens)",
    "Заголовок: двоеточие, запятая, точка.",
]
IDS = ["t-2026-01-01-slug", "t-2026-12-31-a-b-c-2", "local-008"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "state,prio,tid,title",
    list(itertools.product(STATES, PRIOS, IDS, TITLES)),
)
def test_round_trip(state, prio, tid, title):
    """parse(format(x)) == x на всех состояниях, приоритетах и типах заголовков."""
    head = grammar.Head(state=state, prio=prio, task_id=tid, title=title)
    line = grammar.format_head(head)
    parsed = grammar.parse_head(line)
    assert parsed is not None, f"не разобралось: {line!r}"
    assert parsed == head
    assert grammar.format_head(parsed) == line


@pytest.mark.unit
def test_priority_is_optional():
    """Блок без приоритета — валидный: такие есть в живой очереди."""
    line = "- [x] t-2026-08-04-bytovki-hours — Учесть время"
    head = grammar.parse_head(line)
    assert head is not None
    assert head.prio is None
    assert head.state == "x"


@pytest.mark.unit
def test_non_task_lines_are_rejected():
    for line in (
        "## Заголовок раздела",
        "      role: developer",
        "- обычный пункт списка",
        "- [ ] чеклист без идентификатора",
        "",
    ):
        assert grammar.parse_head(line) is None, f"ошибочно принято: {line!r}"


@pytest.mark.unit
def test_reader_and_writer_share_the_grammar():
    """Парсер очереди и модуль записи используют один источник формы.

    Модуль грузится по пути из репозитория, а не обычным import: в sys.path
    может оказаться установленная копия из ~/.local/share/brain/lib, и тогда
    тест проверял бы её, а не рабочее дерево.
    """
    import importlib.util
    from brain_core import taskfile

    spec = importlib.util.spec_from_file_location(
        "_parser_under_test", REPO / "runtime" / "lib" / "brain_task_parser.py"
    )
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)

    assert parser.TASK_HEAD_RE is grammar.HEAD_RE
    assert parser.TASK_BLOCK_RE is grammar.BLOCK_RE
    # Модуль записи строит паттерны через грамматику, а не собственным regex.
    assert taskfile._pattern("t-x", "[ ~]").pattern == grammar.head_re_for("t-x", "[ ~]").pattern


@pytest.mark.unit
@pytest.mark.parametrize("prio_part", ["[P1] ", ""])
def test_head_re_for_group_numbers_are_stable(prio_part):
    """Номера групп в head_re_for не зависят от наличия приоритета.

    Группа приоритета там намеренно незахватывающая. Когда она захватывала,
    номера групп съезжали: brain-task take подставлял приоритет вместо строк
    продолжения и терял role/council/acceptance целиком.
    """
    text = (
        f"- [ ] {prio_part}t-2026-01-01-x — Заголовок\n"
        "      role: architect   mode: council\n"
        "      council: [architect, reviewer]\n"
    )
    m = grammar.head_re_for("t-2026-01-01-x", " ").search(text)
    assert m is not None
    assert len(m.groups()) == 3, f"ожидались ровно три группы, а не {m.groups()}"
    assert m.group(1) == "- ["
    assert "t-2026-01-01-x — Заголовок" in m.group(2)
    assert "role: architect" in m.group(3)
    assert "council:" in m.group(3)


@pytest.mark.unit
def test_block_regex_captures_continuation_lines():
    text = (
        "- [ ] [P1] t-2026-01-01-x — Заголовок\n"
        "      role: developer   mode: solo\n"
        "      acceptance: что-то\n"
        "\n"
        "- [ ] [P2] t-2026-01-02-y — Другая\n"
        "      role: reviewer\n"
    )
    # Одна захватывающая группа — блок целиком, поэтому findall отдаёт строки.
    blocks = grammar.BLOCK_RE.findall(text)
    assert len(blocks) == 2
    assert "acceptance" in blocks[0]
    assert "reviewer" in blocks[1]


@pytest.mark.unit
def test_no_inline_task_regex_outside_grammar():
    """Форма блока не продублирована в других модулях.

    Ищем характерные куски: литерал `- \\[` вместе с признаком приоритета или
    состояния. Именно такие инлайн-паттерны и разъезжались.
    """
    suspicious = re.compile(r"- \\\[.*(?:P\[0123\]|\[ ~x!\]|\\w\*?\])")
    offenders = []
    for path in itertools.chain(
        (REPO / "runtime" / "lib").rglob("*.py"),
        (REPO / "runtime" / "mcp").rglob("*.py"),
    ):
        if path.name == "grammar.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if suspicious.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert not offenders, "инлайн-regex блока задачи вне grammar.py:\n" + "\n".join(offenders)


@pytest.mark.unit
def test_live_queue_round_trips():
    """Каждый блок реальной очереди разбирается и собирается обратно без потерь."""
    for name in ("tasks/active.md", "tasks/done.md"):
        path = REPO / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("- ["):
                continue
            head = grammar.parse_head(line)
            assert head is not None, f"{name}: не разобрано {line[:70]!r}"
            assert grammar.format_head(head) == line, f"{name}: не совпало {line[:70]!r}"


# --- поле против прозы -------------------------------------------------------

def test_parse_fields_reads_several_fields_in_one_line():
    from brain_core.grammar import parse_fields

    got = parse_fields("      role: lawyer   mode: solo   client: ООО Ромашка")
    assert got == {"role": "lawyer", "mode": "solo", "client": "ООО Ромашка"}


def test_parse_fields_ignores_field_name_mentioned_in_prose():
    """Имя поля в тексте задачи полем не становится.

    Разбор шёл `re.search` по всей строке без привязки, и последнее вхождение
    затирало настоящее значение — поля стоят выше прозы.
    """
    from brain_core.grammar import parse_fields

    assert parse_fields("      Дела вынесены, `client:` в корневой очереди запрещён.") == {}
    assert parse_fields("      Здесь role: часть фразы, а не поле") == {}


def test_parse_fields_requires_line_start_or_two_spaces():
    from brain_core.grammar import parse_fields

    assert parse_fields("role: developer") == {"role": "developer"}
    assert parse_fields("      role: developer") == {"role": "developer"}
    # Один пробел перед ключом — это текст, а не поле.
    assert "mode" not in parse_fields("      role: developer mode: solo")


def test_parse_fields_reads_head_line_form_from_memory_md():
    from brain_core.grammar import parse_fields

    line = "- [ ] [P1] t-id — Название               role: developer  mode: solo  due: 2026-05-15"
    got = parse_fields(line)
    assert got["role"] == "developer"
    assert got["mode"] == "solo"
    assert got["due"] == "2026-05-15"


def test_parse_fields_ignores_field_like_metadata_inside_inline_code():
    from brain_core.grammar import parse_fields

    line = "acceptance: write `role: developer   depends_on: [task-a]` verbatim   role: developer"
    got = parse_fields(line)
    assert got == {
        "acceptance": "write `role: developer   depends_on: [task-a]` verbatim",
        "role": "developer",
    }


def test_parse_fields_masks_multiple_backticked_metadata_like_fields():
    from brain_core.grammar import parse_fields

    line = (
        "role: developer   acceptance: see `role: x   depends_on: [a]   mode: solo` "
        "and `client: ACME`   depends_on: [task-a]"
    )
    got = parse_fields(line)
    assert got == {
        "role": "developer",
        "acceptance": "see `role: x   depends_on: [a]   mode: solo` and `client: ACME`",
        "depends_on": "[task-a]",
    }


def test_parse_fields_inline_code_at_line_start_does_not_mask_after():
    from brain_core.grammar import parse_fields

    line = "`depends_on: [task-a]`   role: developer   depends_on: [task-b]"
    assert parse_fields(line) == {"role": "developer", "depends_on": "[task-b]"}


def test_parse_fields_unmatched_backtick_masks_nothing():
    from brain_core.grammar import parse_fields

    # A lone backtick is not a span; a real field after it must survive
    # and not be swallowed into prose by a greedy end-of-line mask.
    line = "      acceptance: note ` alone   role: developer   depends_on: [task-a]"
    got = parse_fields(line)
    assert got == {
        "acceptance": "note ` alone",
        "role": "developer",
        "depends_on": "[task-a]",
    }


def test_parse_fields_and_count_field_starts_agree_on_inline_code():
    from brain_core.grammar import count_field_starts, parse_fields

    line = (
        "acceptance: write `role: developer   depends_on: [task-a]` verbatim"
        "   role: developer   depends_on: [task-b]"
    )
    assert parse_fields(line) == {
        "acceptance": "write `role: developer   depends_on: [task-a]` verbatim",
        "role": "developer",
        "depends_on": "[task-b]",
    }
    assert count_field_starts(line, "acceptance") == 1
    assert count_field_starts(line, "role") == 1
    assert count_field_starts(line, "depends_on") == 1


def test_count_field_starts_ignores_backticked_mentions():
    from brain_core.grammar import count_field_starts

    line = (
        "acceptance: document `role: developer   depends_on: [task-a]`"
        "   role: developer   depends_on: [task-a]"
    )
    assert count_field_starts(line, "depends_on") == 1
    assert count_field_starts(line, "role") == 1


def test_count_field_starts_masks_multiple_backticked_metadata_like_fields():
    from brain_core.grammar import count_field_starts

    line = (
        "role: developer   acceptance: see `role: x   depends_on: [a]   mode: solo` "
        "and `client: ACME`   depends_on: [task-a]"
    )
    assert count_field_starts(line, "depends_on") == 1
    assert count_field_starts(line, "role") == 1


def test_count_field_starts_unmatched_backtick_masks_nothing():
    from brain_core.grammar import count_field_starts

    line = "      acceptance: note ` alone   role: developer   depends_on: [task-a]"
    assert count_field_starts(line, "depends_on") == 1
    assert count_field_starts(line, "role") == 1
