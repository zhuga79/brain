#!/usr/bin/env python3
"""Install and verify the managed Brain MCP runtime tree.

Установка обязана переживать прерывание. Раньше install сначала вычищал
установленный каталог и только потом копировал новое дерево: Ctrl-C, падение
или отключение питания посреди копирования оставляли живой MCP-пакет
разобранным. Пока этим путём ходили руками, риск был приемлем; после того как
setup/update стали обновлять существующую установку через тот же install, это
стало штатной операцией.

Протокол теперь такой:

1. Новое дерево целиком собирается в staging-каталоге ВНУТРИ install_root —
   значит, на той же файловой системе, и подмена делается переименованиями,
   а не копированием.
2. В staging пишется manifest.json, после чего staging проверяется по
   манифесту (состав + sha256 каждого файла). Не сошлось — установка падает,
   не тронув установленное дерево.
3. Подмена идёт по журналу `.brain-mcp-swap.json`: сначала он фиксирует
   намерение (что убираем в backup, что вносим из staging), затем идут
   переименования верхнеуровневых записей, затем журнал удаляется — это и
   есть точка фиксации. Пока журнал на месте, установка считается
   незавершённой, и следующий install (или `recover`) детерминированно
   откатывает её к предыдущему состоянию.

Полностью атомарной подмена не является: `runtime/` уходит в backup и
приходит из staging двумя соседними rename(2) (одиночный rename не умеет
подменять непустой каталог). Гарантируется другое — состояние всегда
восстановимо: любая точка обрыва либо оставляет прежнюю установку, либо
описана журналом и откатывается к ней.

`.venv` не участвует в подмене вообще: он лежит в install_root рядом с
`runtime/` и никогда не переименовывается, поэтому вшитые в него абсолютные
пути остаются верными.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator


MANAGED_ROOTS = ("runtime/mcp", "runtime/lib")
MANIFEST_NAME = "manifest.json"
EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
PRESERVED_TOP_LEVEL = {".venv"}

# Служебные записи install_root. Их не видит ни verify, ни подсчёт extras:
# иначе брошенный после сбоя backup выглядел бы как дрейф установки, а
# staging параллельного install — как мусор, который надо снести.
STAGE_PREFIX = ".brain-mcp-stage-"
BACKUP_PREFIX = ".brain-mcp-backup-"
JOURNAL_NAME = ".brain-mcp-swap.json"
JOURNAL_SCHEMA = "brain-mcp-swap-journal-v1"
INTERNAL_PREFIXES = (STAGE_PREFIX, BACKUP_PREFIX, JOURNAL_NAME)

# Верхнеуровневые записи полезной нагрузки. Их подменяем последними на выходе
# и первыми на входе, чтобы окно, в котором `runtime/` отсутствует, состояло
# ровно из двух соседних rename(2) без посторонних шагов между ними.
PAYLOAD_TOP_LEVEL = tuple(sorted({Path(root).parts[0] for root in MANAGED_ROOTS}))


class InstallError(RuntimeError):
    """Staging-дерево не сошлось с манифестом — подмену не начинаем."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_internal(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in INTERNAL_PREFIXES)


def _iter_source_files(system_root: Path) -> Iterable[Path]:
    for root_name in MANAGED_ROOTS:
        root = system_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIRS for part in path.relative_to(system_root).parts):
                continue
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            yield path


def source_manifest(system_root: Path) -> dict:
    files = {
        str(path.relative_to(system_root)): _sha256(path)
        for path in _iter_source_files(system_root)
    }
    return {
        "schema": "brain-mcp-install-manifest-v1",
        "files": files,
        "file_count": len(files),
    }


def _manifest_text(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _installed_files(install_root: Path) -> list[str]:
    files: list[str] = []
    if not install_root.exists():
        return files
    for path in sorted(install_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(install_root)
        if rel.parts and (rel.parts[0] in PRESERVED_TOP_LEVEL or _is_internal(rel.parts[0])):
            continue
        if rel.name == MANIFEST_NAME:
            continue
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(str(rel))
    return files


# --- файловые примитивы -------------------------------------------------
# Вынесены отдельными функциями не ради красоты: тесты подменяют именно их,
# чтобы вносить сбой на конкретном шаге (копирование, переименование).


def _copy_file(source: Path, target: Path) -> None:
    shutil.copy2(source, target)


def _rename(source: Path, target: Path) -> None:
    os.rename(source, target)


def _discard(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _fsync_file(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_enabled() -> bool:
    # Отключаемо для окружений, где fsync стоит дорого (сетевые ФС в CI).
    # По умолчанию включено: без сброса данных на диск rename переживёт
    # отключение питания, а содержимое файлов — нет.
    return os.environ.get("BRAIN_MCP_FSYNC", "1") != "0"


def _fsync_tree(root: Path) -> None:
    if not _fsync_enabled():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            _fsync_file(path)
        elif path.is_dir():
            _fsync_dir(path)
    _fsync_dir(root)


@contextmanager
def _install_lock(install_root: Path) -> Iterator[bool]:
    """Сериализовать install/recover по одному install_root.

    Лок берётся flock'ом на дескриптор самого каталога: отдельного lock-файла
    нет, значит и мусора после успешного прогона нет. Под локом любой
    найденный staging/backup заведомо брошен упавшим прогоном, а не занят
    соседним.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - не Linux/BSD
        yield False
        return
    try:
        fd = os.open(install_root, os.O_RDONLY)
    except OSError:  # pragma: no cover - каталог исчез между mkdir и open
        yield False
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield True
    finally:
        os.close(fd)


# --- журнал подмены -----------------------------------------------------


def _write_journal(install_root: Path, journal: dict) -> None:
    path = install_root / JOURNAL_NAME
    tmp = install_root / (JOURNAL_NAME + ".tmp")
    tmp.write_text(json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if _fsync_enabled():
        _fsync_file(tmp)
    os.replace(tmp, path)
    if _fsync_enabled():
        _fsync_dir(install_root)


def _read_journal(install_root: Path) -> dict | None:
    path = install_root / JOURNAL_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _valid_journal(journal: dict) -> bool:
    if journal.get("schema") != JOURNAL_SCHEMA:
        return False
    if not isinstance(journal.get("stage"), str) or not isinstance(journal.get("backup"), str):
        return False
    for key in ("incoming", "replaced"):
        value = journal.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False
    for key in ("stage", "backup"):
        name = journal[key]
        if not _is_internal(name) or "/" in name or name in {".", ".."}:
            return False
    return True


def _clear_journal(install_root: Path) -> None:
    try:
        (install_root / JOURNAL_NAME).unlink()
    except FileNotFoundError:
        pass
    if _fsync_enabled():
        _fsync_dir(install_root)


# --- подмена и откат ----------------------------------------------------


def _payload_last(name: str) -> tuple[int, str]:
    return (1 if name in PAYLOAD_TOP_LEVEL else 0, name)


def _payload_first(name: str) -> tuple[int, str]:
    return (0 if name in PAYLOAD_TOP_LEVEL else 1, name)


def _managed_top_level(install_root: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in install_root.iterdir()
        if entry.name not in PRESERVED_TOP_LEVEL and not _is_internal(entry.name)
    )


def _swap_in_stage(install_root: Path, stage: Path) -> None:
    backup = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=install_root))
    incoming = sorted((entry.name for entry in stage.iterdir()), key=_payload_first)
    replaced = sorted(_managed_top_level(install_root), key=_payload_last)
    journal = {
        "schema": JOURNAL_SCHEMA,
        "stage": stage.name,
        "backup": backup.name,
        "incoming": incoming,
        "replaced": replaced,
    }
    _write_journal(install_root, journal)
    try:
        # Всё лишнее (extras прошлой установки) уезжает в backup вместе с
        # заменяемым: откат вернёт установку ровно в прежний вид, а успешная
        # подмена снесёт backup целиком — extras при этом исчезают.
        for name in replaced:
            _rename(install_root / name, backup / name)
        for name in incoming:
            _rename(stage / name, install_root / name)
    except BaseException:
        # Ctrl-C сюда тоже приходит: откат обязателен и для него.
        try:
            _rollback(install_root, journal)
        except Exception:
            # Откат не удался — журнал остаётся, его доиграет `recover`.
            pass
        raise
    if _fsync_enabled():
        _fsync_dir(install_root)
    _clear_journal(install_root)
    shutil.rmtree(backup, ignore_errors=True)


def _rollback(install_root: Path, journal: dict) -> None:
    """Вернуть install_root в состояние, зафиксированное журналом.

    Для каждой верхнеуровневой записи возможны ровно три места: install_root
    (прежняя или уже новая версия), backup (прежняя, если её успели убрать),
    stage (новая, если её ещё не внесли). Наличие записи в backup — признак
    того, что подмена этого имени началась.
    """
    stage = install_root / journal["stage"]
    backup = install_root / journal["backup"]
    incoming = list(journal["incoming"])
    replaced = list(journal["replaced"])
    replaced_set = set(replaced)

    for name in incoming:
        target = install_root / name
        saved = backup / name
        if name in replaced_set:
            if saved.exists() or saved.is_symlink():
                _discard(target)
                _rename(saved, target)
        else:
            # Прежде такой записи не было: всё, что появилось, — новое.
            _discard(target)

    for name in replaced:
        if name in incoming:
            continue
        saved = backup / name
        if saved.exists() or saved.is_symlink():
            _discard(install_root / name)
            _rename(saved, install_root / name)

    if _fsync_enabled():
        _fsync_dir(install_root)
    _clear_journal(install_root)
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)


def _drop_orphan_temp(install_root: Path) -> list[str]:
    dropped: list[str] = []
    for entry in sorted(install_root.iterdir()):
        if not _is_internal(entry.name):
            continue
        _discard(entry)
        dropped.append(entry.name)
    return dropped


def _recover_locked(install_root: Path) -> dict:
    journal = _read_journal(install_root)
    if journal is not None and not _valid_journal(journal):
        # Журнал нечитаем: откатывать наугад нельзя, но и блокировать
        # установку незачем — install перезапишет дерево целиком. Служебные
        # каталоги оставляем человеку на разбор.
        _clear_journal(install_root)
        return {"status": "unreadable-journal", "recovered": False, "dropped": []}
    recovered = False
    if journal is not None:
        _rollback(install_root, journal)
        recovered = True
    return {"status": "ok", "recovered": recovered, "dropped": _drop_orphan_temp(install_root)}


def recover_install(install_root: Path) -> dict:
    """Доиграть прерванную подмену и убрать брошенные служебные каталоги."""
    install_root = Path(install_root)
    if not install_root.is_dir():
        return {"status": "ok", "recovered": False, "dropped": []}
    with _install_lock(install_root):
        return _recover_locked(install_root)


# --- staging ------------------------------------------------------------


def _populate_stage(system_root: Path, stage: Path, manifest: dict) -> None:
    for rel_path in manifest["files"]:
        source = system_root / rel_path
        target = stage / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(source, target)
    (stage / MANIFEST_NAME).write_text(_manifest_text(manifest), encoding="utf-8")


def _verify_stage(stage: Path, manifest: dict) -> None:
    expected = manifest["files"]
    staged = {rel: _sha256(stage / rel) for rel in _installed_files(stage)}
    missing = sorted(set(expected) - set(staged))
    extras = sorted(set(staged) - set(expected))
    mismatches = sorted(path for path in set(expected) & set(staged) if staged[path] != expected[path])
    if missing or extras or mismatches:
        raise InstallError(
            "staged tree does not match its manifest: "
            f"missing={missing[:5]} extras={extras[:5]} mismatches={mismatches[:5]}"
        )
    try:
        written = json.loads((stage / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"staged manifest unreadable: {exc}") from exc
    if written.get("files") != expected or written.get("file_count") != manifest["file_count"]:
        raise InstallError("staged manifest disagrees with the source manifest")


def install_tree(system_root: Path, install_root: Path) -> dict:
    system_root = Path(system_root)
    install_root = Path(install_root)
    manifest = source_manifest(system_root)
    install_root.mkdir(parents=True, exist_ok=True)
    with _install_lock(install_root):
        recovery = _recover_locked(install_root)
        stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=install_root))
        try:
            _populate_stage(system_root, stage, manifest)
            _fsync_tree(stage)
            _verify_stage(stage, manifest)
            _swap_in_stage(install_root, stage)
        finally:
            # После удачной подмены staging пуст: его записи переехали
            # переименованием. После сбоя — здесь же уходит недособранное.
            shutil.rmtree(stage, ignore_errors=True)
    return {"status": "ok", "recovered": bool(recovery["recovered"]), **manifest}


def verify_install(system_root: Path, install_root: Path) -> dict:
    manifest = source_manifest(system_root)
    expected = manifest["files"]
    present = _installed_files(install_root)
    present_set = set(present)
    expected_set = set(expected)
    missing = [{"path": path} for path in sorted(expected_set - present_set)]
    extras = [{"path": path} for path in sorted(present_set - expected_set)]
    mismatches = []
    for path in sorted(expected_set & present_set):
        installed = install_root / path
        digest = _sha256(installed)
        if digest != expected[path]:
            mismatches.append({"path": path, "expected": expected[path], "installed": digest})
    drift_count = len(missing) + len(extras) + len(mismatches)
    return {
        "status": "ok" if drift_count == 0 else "drift",
        "file_count": manifest["file_count"],
        "missing": missing,
        "extras": extras,
        "mismatches": mismatches,
        "drift_count": drift_count,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or verify the Brain MCP runtime tree")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "verify", "manifest", "recover"):
        sub = subparsers.add_parser(name)
        if name != "recover":
            sub.add_argument("--system-root", required=True)
        if name != "manifest":
            sub.add_argument("--install-root", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "manifest":
        system_root = Path(args.system_root).resolve()
        print(json.dumps(source_manifest(system_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    install_root = Path(args.install_root).resolve()
    if args.command == "recover":
        print(json.dumps(recover_install(install_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    system_root = Path(args.system_root).resolve()
    if args.command == "install":
        print(json.dumps(install_tree(system_root, install_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = verify_install(system_root, install_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
