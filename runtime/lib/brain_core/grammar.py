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
    "model", "ref",
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


def parse_fields(line: str) -> dict[str, str]:
    """Поля одной строки блока: имя → значение.

    Проза, упоминающая имя поля, полем не становится: в `` `client:` в корне``
    ключу предшествует обратная кавычка, а не пробелы. Цена правила — строка,
    где имя поля стоит после двух пробелов, всё ещё читается как поле; такой
    признак от настоящего поля неотличим.
    """
    starts = [(m.start(1), m.end(), m.group(1)) for m in _FIELD_START.finditer(line)]
    out: dict[str, str] = {}
    for i, (_, value_at, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(line)
        out[name] = line[value_at:end].strip()
    return out


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
