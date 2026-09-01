"""t-2026-08-14-pytest-system-path-isolation: прогон не зависит от шелла оператора.

У оператора `~/.config/brain/env` экспортирует `BRAIN_PATH` и
`BRAIN_SYSTEM_PATH`. Тесты создают пустое дерево в `tmp_path` и проверяют
поведение «конфигурации нет»: `matrix_path` без `$BRAIN/config/routing.json`
обязан пожаловаться, `validate_routing` — увидеть пустой корень. Но
`brain_system_path()` читает `BRAIN_SYSTEM_PATH` из окружения, и при
выставленной переменной пустое дерево молча получало роли, роутинг и доктрину
из боевого системного чекаута. Семнадцать тестов падали ровно поэтому — то
есть результат прогона определялся тем, из какого шелла его запустили.

Наследование окружения снимается здесь один раз для всего каталога, а не
пофайлово: любой новый тест по умолчанию видит чистые корни. Тому, кому нужен
разделённый layout, переменные выставляет собственная фикстура — она
отработает после этой (autouse-фикстуры инстанцируются раньше явно
запрошенных в той же области) и её `monkeypatch` откатится в конце теста.

Отдельно снимается `BRAIN_ENV_FILE` и ставится `BRAIN_SKIP_OPERATOR_ENV`:
иначе подпроцесс, запущенный тестом, дочитал бы корни оператора из файла в
обход уже очищенного окружения.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Переменные, которые переопределяют корни Brain. Их значение обязано
# приходить из теста, а не из шелла.
INHERITED_ROOT_ENV = ("BRAIN_PATH", "BRAIN_SYSTEM_PATH", "BRAIN_ENV_FILE")

# Список провайдерских CLI общий со смоуком: tests/lib/provider-clis.txt.
PROVIDER_CLIS_FILE = Path(__file__).resolve().parent.parent / "lib" / "provider-clis.txt"

STUB_BODY = """#!/usr/bin/env bash
# Заглушка провайдерского CLI (tests/python/conftest.py).
case "${{1:-}}" in
    --version|-v|version) echo "{name} 0.0.0-test-stub"; exit 0 ;;
esac
exit 0
"""


def _provider_clis() -> list[str]:
    lines = PROVIDER_CLIS_FILE.read_text(encoding="utf-8").splitlines()
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


@pytest.fixture(scope="session")
def provider_stub_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Каталог с заглушками провайдерских CLI, один на весь прогон."""
    target = tmp_path_factory.mktemp("provider-stubs")
    for name in _provider_clis():
        stub = target / name
        stub.write_text(STUB_BODY.format(name=name), encoding="utf-8")
        stub.chmod(0o755)
    return target


@pytest.fixture(autouse=True)
def isolate_brain_roots(monkeypatch: pytest.MonkeyPatch, provider_stub_bin: Path) -> None:
    """Убрать корни оператора из окружения теста и его подпроцессов.

    Заодно фиксируется состав провайдерских CLI. `resolve_for_role` решает,
    брать ли кандидата, по наличию его команды на PATH (`shutil.which`), и
    27 тестов маршрутизации проходили только потому, что у оператора
    установлены claude, codex, gemini и opencode. На чистом раннере те же
    тесты видели пустой PATH, резолвер уходил в defaults.cli — и прогон,
    который считался эталоном (1516 passed), был бы красным в CI.
    Набор задаёт песочница: каталог заглушек идёт первым и перекрывает
    настоящие CLI, если они на машине есть.
    """
    for name in INHERITED_ROOT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BRAIN_SKIP_OPERATOR_ENV", "1")
    monkeypatch.setenv(
        "PATH", f"{provider_stub_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    # brain_core.autosave records Path.cwd() as an executor's worktree at lock
    # time and tags it on eviction. In pytest cwd is the live checkout, so any
    # test exercising take/claim_lock/reconcile would leave wip-recovery/<tid>
    # tags in it. test_autosave.py clears this to exercise the module for real.
    monkeypatch.setenv("BRAIN_AUTOSAVE_DISABLE", "1")
