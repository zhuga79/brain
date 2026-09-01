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
capture_output _bs_text 'brain-status'
grep -q "^Brain: " <<< "$_bs_text" || { echo "FAILED: brain-status text output missing Brain header"; exit 1; }
capture_output _bs_json 'brain-status --json'
grep -q '"tasks"' <<< "$_bs_json" || { echo "FAILED: brain-status json output missing tasks"; exit 1; }
grep -q '"cli_parity"' <<< "$_bs_json" || { echo "FAILED: brain-status json output missing cli_parity"; exit 1; }
grep -q '"mcp_parity"' <<< "$_bs_json" || { echo "FAILED: brain-status json output missing mcp_parity"; exit 1; }

echo ">>> Verifying split-root doctrine and skill listing from data cwd"
split_td=$(mktemp -d)
split_brain="$split_td/data"
mkdir -p "$split_brain"/{tasks,wiki,council,raw,prd,teams,.locks}
printf '# active\n' > "$split_brain/tasks/active.md"
printf '# done\n' > "$split_brain/tasks/done.md"
printf '# log\n' > "$split_brain/wiki/log.md"
(
  export BRAIN_PATH="$split_brain"
  export BRAIN_SYSTEM_PATH="$PROJECT_ROOT"
  capture_output _dl 'brain-doctrine list'
  grep -q '^tax-boundaries$' <<< "$_dl" || {
    echo "FAILED: brain-doctrine list does not see system doctrine from data cwd"
    exit 1
  }
  capture_output _dr 'brain-doctrine roles'
  grep -q '^developer$' <<< "$_dr" || {
    echo "FAILED: brain-doctrine roles does not see system roles from data cwd"
    exit 1
  }
  capture_output _sl 'brain-skill list'
  grep -q 'frontend-handoff-spec' <<< "$_sl" || {
    echo "FAILED: brain-skill list does not see system skills from data cwd"
    exit 1
  }
)
rm -rf "$split_td"

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
