"""Атомарная запись файлов и межпроцессная блокировка.

Собрано из brain_launch_queue и brain_core.taskfile, где один и тот же приём
был реализован дважды. Приём везде один: писать во временный файл рядом,
fsync, затем os.replace — читатель видит либо старое содержимое целиком, либо
новое, но никогда половину.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any


@contextlib.contextmanager
def file_lock(lock_path: Path):
    """Межпроцессная блокировка на отдельном файле.

    Блокируется именно отдельный файл, а не тот, который пишется: flock живёт
    на inode, а os.replace подставляет новый inode, поэтому блокировка на
    целевом файле терялась бы ровно в момент записи.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write_text(path: Path, text: str, *, prefix: str = ".tmp.") -> None:
    """Записать текст целиком, без промежуточного состояния на диске."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_json(path: Path, data: Any) -> None:
    """То же для JSON — с переводом строки в конце, чтобы файл был diff-friendly."""
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_text(path: Path, default: str = "", *, errors: str = "replace") -> str:
    """Прочитать текст. Нет файла — default; битый UTF-8 заменяется, не роняет.

    `errors="replace"` совпадает с чтением очереди до e46226f (дашборд и
    brain-shell): повреждённый active.md не должен валить collect_status.
    """
    try:
        return path.read_text(encoding="utf-8", errors=errors)
    except FileNotFoundError:
        return default


def read_json(path: Path, default: Any = None) -> Any:
    """Прочитать JSON, вернув default при отсутствии или повреждении."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default
