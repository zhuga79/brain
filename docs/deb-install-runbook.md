---
title: Runbook — установка .deb и встречный sync
type: runbook
created: 2026-09-04
updated: 2026-09-04
curation: agent
protected: false
source_policy: advisory
tags: [runbook, deb, packaging, federation, sync, operator]
sources: []
related: [federation-sync, decision-multi-user-federation, cli-cheatsheet]
visibility: public
---

# Runbook: `.deb` и встречный sync

## Собрать пакет

Из чистого клона репозитория, нужны `dpkg-deb` и `fakeroot`:

```sh
bash runtime/packaging/build-deb.sh
# -> dist/brain-runtime_<version>_all.deb
```

Версия берётся из `pyproject.toml` и сверяется с верхней строкой
`debian/changelog` — расхождение останавливает сборку. Бампишь версию —
правишь оба файла.

## Установить на чистую машину

Debian 12+/Ubuntu 22.04+; `apt` сам подтянет зависимости (`python3 (>= 3.10)`,
`git`, `jq`):

```sh
sudo apt-get install ./brain-runtime_<version>_all.deb
```

Проверка:

```sh
command -v brain-task brain-validate brain-federation   # все в /usr/bin
python3 -c "import brain_core.version"                   # из dist-packages, без PYTHONPATH
brain-status | grep '^Core:'                             # Core: <version> (dpkg:brain-runtime)
```

`Core: unpackaged` или команда не в `PATH` — установка неполная.

Раскладка: библиотека в `/usr/lib/python3/dist-packages`, скрипты и шаблоны в
`/usr/share/brain`, `/usr/bin/brain-*` — обёртки, которые `exec`ают реальный
скрипт (чтобы `dirname "$BASH_SOURCE"` внутри находил `brain-common` и `../`).

## Развернуть вольт

```sh
BRAIN_PATH=/path/to/vault bash /usr/share/brain/setup-brain-v2.sh
brain-validate --brain /path/to/vault
```

## Встречный sync двух узлов

Оба вольта клонированы из общего bare-remote. На каждом задай идентичность
(один раз):

```sh
mkdir -p "$BRAIN_PATH/config"
printf '{"node_id": "node-a"}\n' > "$BRAIN_PATH/config/federation.json"
# либо: export BRAIN_NODE_ID=node-a
```

Цикл на каждом узле:

```sh
brain-federation preflight --repo "$BRAIN_PATH" --brain "$BRAIN_PATH"   # прочитать findings
brain-federation sync --repo "$BRAIN_PATH" --brain "$BRAIN_PATH"
```

`preflight`:

- `federated-lock-warning` (review) — задача, на которой держишь лок, изменена
  на удалённой стороне; сверься перед sync.
- `runtime-file-included` (block) — runtime-файл (`.locks/`, `.brain/`,
  `.provider-health.json`, …) реально уйдёт в синхронизацию; убери из коммита,
  оставь в `.gitignore`.

`sync` при rebase-конфликте на `tasks/active.md` / `tasks/done.md` /
`wiki/log.md` — авто-мерджит по task-id и по строкам журнала. Останавливается
с `federation-sync-queue-conflict`, только если:

- `title`/`role`/`mode`/`acceptance` правлены на обеих сторонах по-разному;
- задача open на одной стороне, done на другой.

Тогда правишь `tasks/active.md` руками и повторяешь `brain-federation sync`.

Автоматизация — `brain-sync-cycle --apply` под systemd-таймером (см.
[[federation-sync]]).
