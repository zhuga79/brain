#!/usr/bin/env bash
# case: shell-injection — метасимволы в идентификаторах не исполняются
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying task/agent ids cannot inject shell commands"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

marker="$BRAIN_FACTORY_TMP/pwned"
rm -f "$marker"

# shellcheck source=/dev/null
source "$PROJECT_ROOT/runtime/bin/brain-common"

# ── 1. build_role_command отвергает метасимволы, а не экранирует их ──
# Легальный идентификатор их не содержит, поэтому отказ честнее попытки
# обезвредить: экранирование и проверка со временем разъезжаются.
for bad in "t-x; touch $marker" 't-x$(id)' 't-x`id`' "t-x
touch $marker" "t-x&touch $marker"; do
  set +e
  out="$(build_role_command developer "$bad" agent-1 claude 2>&1)"
  rc=$?
  set -e
  [ "$rc" -ne 0 ] || {
    echo "FAILED: принят идентификатор задачи с метасимволами: $bad"
    echo "  собрана команда: $out"
    exit 1
  }
done
echo "OK: идентификатор задачи с метасимволами отвергнут"

for bad in "agent; touch $marker" 'agent$(id)'; do
  set +e
  build_role_command developer t-ok "$bad" claude >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" -ne 0 ] || { echo "FAILED: принят идентификатор агента: $bad"; exit 1; }
done
echo "OK: идентификатор агента с метасимволами отвергнут"

set +e
build_role_command "developer; touch $marker" t-ok agent-1 claude >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: принята роль с метасимволами"; exit 1; }
echo "OK: роль с метасимволами отвергнута"

# ── 2. Легальные значения по-прежнему собираются и экранированы ──
cmd="$(build_role_command developer t-2026-08-11-x agent-1.2 claude)"
grep -q "brain-run --role developer" <<< "$cmd" || {
  echo "FAILED: легальная команда не собралась: $cmd"
  exit 1
}
echo "OK: легальные значения проходят"

# ── 3. CLI отвергают такие идентификаторы на входе ──
set +e
brain-task take "t-x; touch $marker" --as probe >/dev/null 2>&1
task_rc=$?
brain-launch "t-x; touch $marker" --dry-run >/dev/null 2>&1
launch_rc=$?
brain-council start "t-x; touch $marker" >/dev/null 2>&1
council_rc=$?
set -e
[ "$task_rc" -ne 0 ] || { echo "FAILED: brain-task принял id с метасимволами"; exit 1; }
[ "$launch_rc" -ne 0 ] || { echo "FAILED: brain-launch принял id с метасимволами"; exit 1; }
[ "$council_rc" -ne 0 ] || { echo "FAILED: brain-council принял id с метасимволами"; exit 1; }
echo "OK: brain-task, brain-launch и brain-council отвергают такие id"

# ── 4. Главное: ничего не исполнилось ──
[ ! -e "$marker" ] || {
  echo "FAILED: команда из идентификатора была исполнена — создан $marker"
  exit 1
}
echo "OK: побочных эффектов нет"

# ── 5. Проверка — одна на всю систему ──
grep -q "validate_id()" "$PROJECT_ROOT/runtime/bin/brain-common" || {
  echo "FAILED: validate_id пропала из brain-common"
  exit 1
}
grep -q "validate_id" "$PROJECT_ROOT/runtime/bin/brain-launch" || {
  echo "FAILED: brain-launch не проверяет id"
  exit 1
}
grep -q "validate_id" "$PROJECT_ROOT/runtime/bin/brain-council" || {
  echo "FAILED: brain-council не проверяет id"
  exit 1
}
echo "OK: проверка подключена во всех точках входа"

echo ">>> shell injection checks passed"
