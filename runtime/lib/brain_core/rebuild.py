"""Постановка ребилда индекса в очередь с подавлением дребезга.

Каждая мутация очереди задач запускала `brain-index rebuild &`. Пять быстрых
операций — пять процессов, одновременно переписывающих `.brain/index/`;
brain-search в этот момент мог прочитать неполный результат.

Здесь ребилд запускается под взаимным исключением: пока один процесс работает,
второй не стартует, а лишь помечает, что данные снова изменились. Работающий
процесс, закончив, видит метку и делает ещё один проход. Поэтому серия быстрых
мутаций сводится к двум ребилдам: текущему и одному завершающему.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from brain_core import atomic, paths

LOCK_NAME = "rebuild.lock"
DIRTY_NAME = "rebuild.dirty"


def _state_dir(brain: Path) -> Path:
    d = brain / ".brain"
    d.mkdir(parents=True, exist_ok=True)
    return d


def request(brain: Path | None = None, binary: str = "brain-index") -> int:
    """Запросить ребилд.

    Возвращает 0, если ребилд выполнен (возможно, несколько проходов), и 0 же,
    если работу взял на себя другой процесс: для вызывающего это одинаково
    успешный исход — индекс будет перестроен.
    """
    root = paths.brain_path(str(brain) if brain else None)
    state = _state_dir(root)
    lock_path = state / LOCK_NAME
    dirty_path = state / DIRTY_NAME

    # Метку ставим всегда и до попытки захвата: если ребилд уже идёт, он
    # увидит её и сделает дополнительный проход с нашими изменениями.
    dirty_path.write_text("1", encoding="utf-8")

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Ребилд уже идёт. Метка выставлена — он подхватит изменения.
            return 0

        env = os.environ.copy()
        env["BRAIN_PATH"] = str(root)
        # Не более двух проходов: первый — по текущим данным, второй — по тем,
        # что пришли во время первого. Дальше нужен уже следующий запрос.
        for _ in range(2):
            if not dirty_path.exists():
                break
            dirty_path.unlink(missing_ok=True)
            subprocess.run([binary, "rebuild"], env=env, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _main(argv: list[str]) -> int:
    binary = argv[0] if argv else "brain-index"
    return request(binary=binary)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
