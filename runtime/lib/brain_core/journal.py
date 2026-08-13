"""Журнал операций — wiki/log.md.

Запись в журнал существовала в трёх независимых реализациях: bash-функция
log_op в brain-common, своя версия в mcp/common.py и третья внутри brain-task.
Формат строки при этом обязан совпадать: журнал читается дашбордом и
brain-task log.

Формат: `## [метка] операция | id | агент | дополнение`
"""

from __future__ import annotations

from pathlib import Path

from brain_core import atomic, clock, paths

LOCK_NAME = ".journal.lock"


def format_entry(op: str, task_id: str = "", agent: str = "", extra: str = "") -> str:
    """Собрать строку журнала. Пустые поля остаются пустыми, но не исчезают:
    разделители позиционные, и потребители режут строку по ним."""
    return f"## [{clock.utc_now()}] {op} | {task_id} | {agent} | {extra}\n"


def append_line(line: str, brain: Path | None = None) -> None:
    """Дописать готовую строку под общей блокировкой журнала.

    Периодические команды пишут строки своей исторической формы
    (`- метка: событие`, `## [метка] queue-cycle | …`). Общей у всех писателей
    обязана быть блокировка, а не разметка: без неё параллельные таймеры,
    читающие файл целиком и переписывающие его, теряют чужую запись.
    """
    log = paths.log_file(brain)
    with atomic.file_lock(log.parent / LOCK_NAME):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")


def append(op: str, task_id: str = "", agent: str = "", extra: str = "",
           brain: Path | None = None) -> None:
    """Дописать запись канонического формата под блокировкой.

    Дописывание короткой строки в конец файла обычно атомарно само по себе,
    но журнал пишут параллельные агенты, а размер записи не ограничен —
    поэтому берётся та же блокировка, что и для очереди.
    """
    append_line(format_entry(op, task_id, agent, extra), brain)


def tail(count: int = 30, brain: Path | None = None) -> list[str]:
    """Последние записи журнала, новые в конце."""
    text = atomic.read_text(paths.log_file(brain))
    entries = [ln for ln in text.splitlines() if ln.startswith("## [")]
    return entries[-count:] if count > 0 else entries


def _main(argv: list[str]) -> int:
    """CLI для bash-слоя: python3 -m brain_core.journal <op> [id] [agent] [extra]"""
    import sys

    if not argv:
        print("usage: journal <op> [task-id] [agent] [extra]", file=sys.stderr)
        return 2
    op = argv[0]
    task_id = argv[1] if len(argv) > 1 else ""
    agent = argv[2] if len(argv) > 2 else ""
    extra = argv[3] if len(argv) > 3 else ""
    append(op, task_id, agent, extra)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv[1:]))
