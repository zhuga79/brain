---
title: Decision — Порт data-root правок setup: .pth всегда, pythonpath в pyproject нет
type: decision
created: 2026-08-31
updated: 2026-08-31
curation: agent
protected: false
source_policy: advisory
tags: [decision, setup, packaging, pytest]
sources: []
related: [decision-post-inversion-cycle, decision-public-source-of-truth, decisions-log]
visibility: public
---

# Decision: порт data-root правок setup

**Статус:** принято
**Задача:** `t-2026-08-15-port-data-root-setup-fixes-to`
**Роль:** developer (`grok-46-dev-setup-i9d6`)
**Источник:** data `1edc5fc` / `b85ba5e` (после инверсии не попали в канон)

## Решение

Две правки жили только в дереве данных и были удалены вместе с installer-тенями
(`bb59739`). По каждой — отдельное решение.

### (1) `setup-brain-v2.sh`: писать `brain-runtime.pth` безусловно после pip — порт

`pip install --user -e` на части машин проходит, на части (Homebrew PEP 668)
отказывает. Пока `.pth` писался только в ветке отказа, успешный pip оставлял
в user site путь прошлого чекаута. Этот путь остаётся в `sys.path`, импорт
идёт из чужой копии, `brain-status` печатает `Core: unpackaged` с путём
из приватного дерева — прямое нарушение критерия
[[decision-post-inversion-cycle]].

Пишем `.pth` всегда, на `SCRIPT_DIR/runtime/lib`, без `Path.resolve()`:
`~/brain` как симлинк на `Документы/Brain/files` иначе выглядит как чужая
копия, хотя это то же дерево.

Покрытие: `test_setup_rewrites_runtime_pth_after_pip`,
`test_setup_pth_writer_does_not_resolve_checkout`,
`test_core_location_is_the_import_path`, `tests/cases/96-reinstall-cli.sh`
(успешный pip, split-root и legacy single-root).

### (2) `pyproject.toml`: `pythonpath = ["runtime/lib"]` — отклонить

Строка помогала голому `pytest` в свежем клоне. Сейчас путь задаётся явно:

- CI: `PYTHONPATH=runtime/lib python3 -m pytest` (лок в `test_public_ci.py`)
- pre-commit: `PYTHONPATH="./runtime/lib"` в `install-hooks.sh`
- смоук: `tests/_lib.sh` экспортирует `PYTHONPATH` на `runtime/lib`

`pythonpath` в ini pytest импортирует дерево даже без установки пакета и без
`.pth`. Это маскирует как раз тот unpackaged-контракт, который чинит (1).
Таймеры systemd всё равно не читают pyproject — им нужен явный `PYTHONPATH`
в unit (`test_core_import_fails_under_a_pth_less_interpreter_without_pythonpath`).

Голый `pytest` в свежем клоне без env по-прежнему требует
`PYTHONPATH=runtime/lib python3 -m pytest`. Это документированный вход, не
скрытый второй путь.

Покрытие отказа: `test_pyproject_does_not_set_pytest_pythonpath`.
