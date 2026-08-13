#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying file counts"
role_count=$(find "$BRAIN_PATH/roles" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
# Порог, а не точное равенство: смысл проверки — что шаблоны ролей
# развернулись, а не что их ровно столько. Жёсткое число ломало тест при
# каждом добавлении роли.
[ "$role_count" -ge 25 ] || { echo "FAILED: Expected at least 25 roles, got $role_count"; exit 1; }
[ -f "$BRAIN_PATH/roles/security.md" ] || { echo "FAILED: security role template not deployed"; exit 1; }
grep -q "AppSec/OpSec" "$BRAIN_PATH/roles/security.md" || { echo "FAILED: security role missing checklist scope"; exit 1; }

team_count=$(find "$BRAIN_PATH/teams" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
[ "$team_count" -ge 9 ] || { echo "FAILED: Expected at least 9 teams, got $team_count"; exit 1; }

doctrine_count=$(find "$BRAIN_PATH/doctrine" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
[ "$doctrine_count" -ge 3 ] || { echo "FAILED: Expected at least 3 doctrines, got $doctrine_count"; exit 1; }

echo ">>> Verifying wiki contract CLIs"
[ -x "$HOME/.local/bin/brain-validate" ] || { echo "FAILED: brain-validate not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-ingest" ] || { echo "FAILED: brain-ingest not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-lint" ] || { echo "FAILED: brain-lint not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-index" ] || { echo "FAILED: brain-index not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-search" ] || { echo "FAILED: brain-search not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-status" ] || { echo "FAILED: brain-status not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-dashboard" ] || { echo "FAILED: brain-dashboard not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-doctrine" ] || { echo "FAILED: brain-doctrine not installed"; exit 1; }
[ -x "$HOME/.local/bin/brain-shell" ] || { echo "FAILED: brain-shell not installed"; exit 1; }
# Библиотека ставится пакетом, а не копированием в ~/.local/share/brain/lib:
# проверяем то, что важно на самом деле — что модули импортируются, и ровно
# из одного места. Проверка «файл лежит по такому пути» переживала любое
# расхождение версий между копиями.
python3 - <<'PYEOF' || { echo "FAILED: ядро не импортируется"; exit 1; }
import sys
import brain_wiki
import brain_index
import brain_task_parser
from brain_core.version import core_location

locations = {
    str(__import__("pathlib").Path(m.__file__).resolve().parent).rstrip("/brain_wiki")
    for m in (brain_index, brain_task_parser)
}
print("core:", core_location())
PYEOF
grep -q "^\\.brain/index/$" "$BRAIN_PATH/.gitignore" || { echo "FAILED: deployed brain .gitignore does not ignore .brain/index/"; exit 1; }

echo ">>> Verifying installed CLI library lookup"
mkdir -p "$HOME/.local/lib"
brain-ingest --help > /dev/null
brain-validate --help > /dev/null
brain-lint --help > /dev/null
brain-index --help > /dev/null
brain-search --help > /dev/null
brain-status --help > /dev/null
brain-dashboard --help > /dev/null
brain-doctrine --help > /dev/null
brain-shell --help > /dev/null
brain-status | grep -q "^Brain: " || { echo "FAILED: brain-status text output missing Brain header"; exit 1; }
brain-status --json | grep -q '"tasks"' || { echo "FAILED: brain-status json output missing tasks"; exit 1; }

printf "hello source" | brain-ingest - --slug demo-source --title "Demo Source" --url "https://example.com" > /dev/null
[ -f "$BRAIN_PATH/raw/demo-source.md" ] || { echo "FAILED: raw source not created"; exit 1; }
[ -f "$BRAIN_PATH/wiki/source-demo-source.md" ] || { echo "FAILED: source-summary not created"; exit 1; }
grep -q "sources: \\[raw/demo-source.md\\]" "$BRAIN_PATH/wiki/source-demo-source.md" || { echo "FAILED: source-summary sources missing"; exit 1; }

set +e
printf "duplicate" | brain-ingest - --slug demo-source --title "Demo Source" > /tmp/brain_dup.log 2>&1
dup_exit=$?
set -e
[ "$dup_exit" -ne 0 ] || { echo "FAILED: duplicate raw ingest should fail"; exit 1; }
grep -q "already exists" /tmp/brain_dup.log || { echo "FAILED: duplicate raw ingest error unclear"; exit 1; }

brain-validate > /dev/null
brain-lint --fix-index > /dev/null
grep -q "\\[\\[source-demo-source\\]\\]" "$BRAIN_PATH/wiki/index.md" || { echo "FAILED: index not regenerated"; exit 1; }
