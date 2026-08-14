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

import pytest

# Переменные, которые переопределяют корни Brain. Их значение обязано
# приходить из теста, а не из шелла.
INHERITED_ROOT_ENV = ("BRAIN_PATH", "BRAIN_SYSTEM_PATH", "BRAIN_ENV_FILE")


@pytest.fixture(autouse=True)
def isolate_brain_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать корни оператора из окружения теста и его подпроцессов."""
    for name in INHERITED_ROOT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BRAIN_SKIP_OPERATOR_ENV", "1")
