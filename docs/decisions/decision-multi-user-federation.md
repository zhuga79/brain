---
title: Decision — Multi-user federation готовность и упаковка в .deb
type: decision
created: 2026-09-04
updated: 2026-09-04
curation: agent
protected: false
source_policy: advisory
tags: [decision, federation, sync, packaging, deb]
sources: []
related: [decisions-log, federation-sync, deb-install-runbook, decision-public-source-of-truth, architecture-overview]
visibility: public
---

# Decision: federation для команды и устанавливаемый пакет

**Статус:** принято
**Задача:** `t-2026-08-16-multi-user-federation-readines` (PRD, 10 сабтасков)
**Роль:** architect
**Родитель:** [[decision-public-source-of-truth]]

## Решение

Двигаться двумя независимыми ветками, которые сходятся только на финальном
smoke и закрытии родителя.

**Ветка F — federation runtime.** Многопользовательский сценарий (двое-пятеро
на одном LAN-репозитории хранилища) доводится до состояния «без потери данных»:

- **Идентичность узла** — `config/federation.json` / `$BRAIN_NODE_ID` с
  фолбэком на `git user.email` **только по явному opt-in** и на `anonymous` по
  умолчанию. Значение пишется в `node=…` аудит-строк `wiki/log.md`.
- **Конфликт лока не разрешается молча** — `brain-lock acquire` отказывает по
  свежему удалённому `[~]` чужого узла; preflight выдаёт
  `federated-lock-warning`; import/plan помечают удалённый `[~]` как block.
- **Слияние `wiki/log.md`** — git-драйвер `brain-log`: append-only,
  коммутативное объединение, дедуп по `(ts, op, task_id, agent, node, extra)`,
  детерминированный порядок.
- **Слияние очередей при rebase-конфликте** — по task-id, не по позиции строк:
  прогресс состояния (`x`>`~`>`!`>open) побеждает, односторонняя правка поля
  берётся, задача не теряется. Два расхождения (правка поля с обеих сторон;
  open↔done) блокируют sync и абортят rebase с чистым деревом.

Механика — [[federation-sync]].

**Ветка D — упаковка в .deb.** `brain-runtime` собирается в устанавливаемый
`.deb` из **канонического источника** (репозиторий, не установленное дерево):

- `debian/` — рабочий debhelper-скелет; `runtime/packaging/build-deb.sh`
  собирает `dist/brain-runtime_<version>_all.deb` через `dpkg-deb` +
  `fakeroot`, версия из `pyproject.toml` (сверяется с `debian/changelog`).
- FHS-раскладка: библиотека → `/usr/lib/python3/dist-packages`, скрипты и
  шаблоны → `/usr/share/brain`, CLI → тонкие обёртки в `/usr/bin`.
- `brain_core.version.core_version()` получает fallback на `dpkg-query`, когда
  `importlib.metadata` пуста; `brain-status` печатает
  `Core: <version> (dpkg:brain-runtime)`.
- Прогон установки в чистых контейнерах `debian:stable` и `ubuntu:latest` —
  CI job `deb-install`.

Инструкция оператора — [[deb-install-runbook]].

## Обоснование декомпозиции

- Ветки F и D не делят файлы — D можно вести другим провайдером параллельно.
- Один монолитный тикет не влезает в сессию и не распараллеливается.
- Сначала-вся-federation-потом-packaging — искусственная сериализация.

## Риски

- **Идентичность самопровозглашённая.** `node=…` — аудит-подсказка, не
  аутентификация: узел называет себя сам, никто это не проверяет. Осознанный
  выбор — сетевой арбитраж локов вне scope.
- **Merge-драйвер живёт в `.git/`.** Он ставится `brain-federation sync` в
  локальный `.git/info/attributes`; свежий клон без прогона sync разрешает
  конфликт `wiki/log.md` обычным git — то есть плохо. Смягчение: `sync`
  ставит драйвер идемпотентно на каждом запуске.
- **`.deb` без `.dist-info`.** Версия читается через `dpkg-query`; на машине,
  где рядом стоит editable-копия, fallback не срабатывает (сначала проверяются
  `metadata` и `.pth`, и `dpkg -S` подтверждает владение конкретным файлом).
- **Контейнерная проверка — единственная.** Docker недоступен в песочнице
  разработки; зелёный прогон `.deb` подтверждается только на CI.

## Отвергнутые альтернативы

- **Распределённый lock-протокол** (сетевой арбитраж) — остаётся ревью-based.
- **CRDT-очередь задач** — избыточно для 2–5 человек на одном репозитории.
- **`fpm` вместо нативного `debian/`** — тянет ruby в toolchain; `dpkg-deb`
  даёт воспроизводимость без внешнего сборщика.
- **Node-id из hostname** — ненадёжно (совпадения, переименования).
- **Публикация пакета в APT/PPA** — сборка артефакта да, публикация нет.
- **Пакеты под не-Debian** (rpm, brew, nix) — вне scope.
