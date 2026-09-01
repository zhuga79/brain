"""Грамматика блока задачи — одна на всех читателей и писателей.

Раньше форма блока была записана в нескольких местах и по-разному: читатель
(brain_task_parser) требовал `\\[P[0123]\\]`, писатели ставили `\\w+` (take),
`\\w*` (block) и `[~ x]` (complete). Задача, записанная вне читательской
грамматики, сохранялась успешно и молча выпадала из `brain-task next`,
дашборда, индекса и MCP.

Поэтому приоритет здесь необязателен: в очереди действительно встречаются
блоки без него, и правильнее их видеть, чем делать вид, что их нет.

Форма блока:

    - [состояние] [приоритет] идентификатор — заголовок
          поле: значение
          свободный текст

Состояние: ` ` открыта, `~` в работе, `x` закрыта, `!` заблокирована.
Продолжение блока — строки с отступом ровно в шесть пробелов.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import NamedTuple

STATES = " ~x!"
"""Допустимые состояния задачи."""

INDENT = "      "
"""Отступ строк продолжения блока. Шесть пробелов — исторический формат."""

_STATE = r"[ ~x!]"
_PRIO = r"(?:\[(P\d)\]\s*)?"
# Та же форма без захвата. Нужна везде, где вызывающий работает с номерами
# групп: захватывающий приоритет сдвигал бы их, и замена подставляла бы
# приоритет вместо строк продолжения блока.
_PRIO_NC = r"(?:\[P\d\]\s*)?"
_CONT = r"(?:\n {6}[^\n]*)*"

HEAD_RE = re.compile(rf"- \[({_STATE})\] {_PRIO}(\S+) — (.+)")
"""Первая строка блока. Группы: состояние, приоритет (может быть None), id, заголовок."""

BLOCK_RE = re.compile(rf"(- \[{_STATE}\] {_PRIO_NC}[^\n]+{_CONT})", re.M)
"""Целый блок: заголовок и строки продолжения. Одна группа — блок целиком."""


def block_re_for(task_id: str, state: str = _STATE) -> re.Pattern:
    """Блок конкретной задачи. `state` — класс символов, например `[~ ]`.

    Идентификатор экранируется: он приходит из аргументов командной строки и
    может содержать метасимволы.
    """
    return re.compile(
        rf"(- \[{state}\] {_PRIO_NC}{re.escape(task_id)} —[^\n]+{_CONT})",
        re.M,
    )


def head_re_for(task_id: str, state: str = _STATE) -> re.Pattern:
    """Заголовок конкретной задачи с разбором на части для замены.

    Группы: открывающая скобка, хвост заголовка, строки продолжения.
    """
    return re.compile(
        rf"^(- \[){state}\](\s*{_PRIO_NC}{re.escape(task_id)} —[^\n]*\n)((?: {{6}}[^\n]*\n)*)",
        re.M,
    )


FIELDS = (
    "role", "mode", "surface", "gate", "council", "depends_on", "deps",
    "parent", "client", "project", "acceptance", "by", "started", "due",
    "model", "ref", "tags", "node", "ttl",
)
"""Имена полей строк продолжения. Нужны, чтобы отличить следующее поле от текста."""

# Длинные имена раньше коротких: иначе `depends_on` совпал бы как `deps`.
_FIELD_ALT = "|".join(sorted(FIELDS, key=len, reverse=True))
_VALUE_END = rf"(?=\s{{2,}}(?:{_FIELD_ALT}):|$)"


@lru_cache(maxsize=None)
def field_re(name: str) -> re.Pattern:
    """Поле со значением, в котором допустимы пробелы.

    Значение тянется до конца строки — но останавливается перед следующим
    полем, если оно записано в той же строке через два и более пробела. Так
    в очереди и оформлены пары вроде `client: ИП Ромашкин   project: Склады`:
    без границы заказчик вбирал в себя весь остаток строки вместе с ключом
    соседнего поля.
    """
    return re.compile(rf"{re.escape(name)}:\s*(.+?)\s*{_VALUE_END}")


# Поле начинается либо с начала строки, либо после двух и более пробелов —
# и вплотную к ним. Иначе полем становилось любое упоминание его имени в
# тексте задачи: разбор шёл `re.search` по всей строке, а последнее вхождение
# затирало настоящее значение, потому что поля стоят выше прозы.
_FIELD_START = re.compile(rf"(?:^|(?<=\s\s))({_FIELD_ALT}):")


def _mask_inline_code(line: str) -> str:
    """Blank the bodies of Markdown inline code spans, preserving offsets.

    Returns a copy with every character strictly between a pair of backtick
    delimiter runs replaced by a space, so the lengths and positions of *line*
    are unchanged. A code span is opened by a run of N consecutive backticks
    and closed by a later run of exactly N backticks; the characters between
    them are masked. Runs of a different length, and runs with no later
    same-length closer, are treated as literal text and mask nothing, so a
    stray or mismatched backtick never hides a real field start. Every
    delimiter run strictly inside a matched span is content and is consumed
    with its span, so it can never pair with a later run outside. Characters
    outside code spans are left as-is, so real field boundaries keep their
    offsets.
    """
    out = list(line)
    runs = _backtick_runs(line)
    consumed: set[int] = set()
    for idx, (start, length) in enumerate(runs):
        if idx in consumed:
            continue
        closer = _next_closer(runs, idx, consumed)
        if closer is None:
            continue
        cstart, _ = runs[closer]
        for i in range(start + length, cstart):
            if out[i] != "\n":
                out[i] = " "
        for k in range(idx, closer + 1):
            consumed.add(k)
    return "".join(out)


def _backtick_runs(line: str) -> list[tuple[int, int]]:
    """Contiguous runs of backticks in *line* as ``(start, length)`` pairs."""
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        runs.append((i, j - i))
        i = j
    return runs


def _next_closer(
    runs: list[tuple[int, int]], opener: int, consumed: set[int]
) -> int | None:
    """Index of the next later run with the same length as ``runs[opener]``.

    Returns None when no same-length closer follows, so an unmatched opener is
    left literal.
    """
    _, length = runs[opener]
    for j in range(opener + 1, len(runs)):
        if j in consumed:
            continue
        if runs[j][1] == length:
            return j
    return None


def _field_starts(line: str) -> list[tuple[int, int, str]]:
    """True field starts on *line*, with Markdown inline code spans ignored.

    ``_FIELD_START`` would otherwise treat a two-space field-like pattern
    inside inline code as a real field. Code spans are masked on a copy
    first; returned offsets still refer to *line* so ``parse_fields`` can
    slice the original values. An unmatched trailing backtick masks nothing.
    """
    masked = _mask_inline_code(line)
    return [(m.start(1), m.end(), m.group(1)) for m in _FIELD_START.finditer(masked)]


def parse_fields(line: str) -> dict[str, str]:
    """Поля одной строки блока: имя → значение.

    Проза, упоминающая имя поля, полем не становится. Имя в обратных кавычках
    (``client:``) не поле, потому что перед ним не два пробела. Текст внутри
    парных обратных кавычек маскируется целиком: даже два пробела перед
    ``depends_on:`` внутри span полем не становятся. Цена правила — имя после
    двух пробелов *вне* inline code всё ещё читается как поле.
    """
    starts = _field_starts(line)
    out: dict[str, str] = {}
    for i, (_, value_at, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(line)
        out[name] = line[value_at:end].strip()
    return out


def count_field_starts(line: str, name: str) -> int:
    """Count how many times *name* appears as a parsed field start on *line*.

    Uses the shared ``_field_starts`` scanner so prose or backticked mentions
    are not counted, including field-like text inside inline code that would
    otherwise look like a real start (two spaces before the name). Only true
    field starts — at line start or after two+ spaces, outside inline code —
    count.
    """
    return sum(1 for _, _, field_name in _field_starts(line) if field_name == name)


class Head(NamedTuple):
    state: str
    prio: str | None
    task_id: str
    title: str


def parse_head(line: str) -> Head | None:
    """Разобрать первую строку блока. None, если строка не заголовок."""
    m = HEAD_RE.match(line)
    if not m:
        return None
    return Head(state=m.group(1), prio=m.group(2), task_id=m.group(3), title=m.group(4))


def format_head(head: Head) -> str:
    """Собрать первую строку блока обратно.

    Обратно к parse_head: format_head(parse_head(x)) == x для любой строки,
    которую parse_head принял.
    """
    prio = f"[{head.prio}] " if head.prio else ""
    return f"- [{head.state}] {prio}{head.task_id} — {head.title}"
