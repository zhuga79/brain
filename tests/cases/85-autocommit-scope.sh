#!/usr/bin/env bash
# case: autocommit-scope — автокоммит трогает только слой данных
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying autocommit stays inside the data layer"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"

bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

cd "$BRAIN_PATH"
git init -q 2>/dev/null || true
git config user.email "smoke@test.local"
git config user.name "Smoke"
git add -A >/dev/null 2>&1 || true
git commit -q -m "base" >/dev/null 2>&1 || true

# ── 1. Правка системного файла во время brain-task не уезжает в автокоммит ──
printf '\n<!-- правка системы во время работы агента -->\n' >> "$BRAIN_PATH/roles/developer.md"
brain-task add "Проверка границы слоёв" --role developer >/dev/null 2>&1

if git diff --quiet HEAD -- roles/developer.md 2>/dev/null; then
  echo "FAILED: правка roles/ попала в автокоммит"
  exit 1
fi
echo "OK: roles/ осталась незакоммиченной"

# Данные при этом закоммичены — иначе мы просто сломали автокоммит.
if ! git log --oneline -1 -- tasks/active.md | grep -q .; then
  echo "FAILED: у tasks/active.md нет ни одного коммита"
  exit 1
fi
if ! git status --porcelain tasks/active.md | grep -q '^$\|^$'; then
  :
fi
if [ -n "$(git status --porcelain tasks/active.md)" ]; then
  echo "FAILED: tasks/active.md остался незакоммиченным после brain-task add"
  git status --porcelain tasks/
  exit 1
fi
echo "OK: tasks/ закоммичены"

# ── 2. Список стажируемых путей — из brain_core.layers ──
paths="$(python3 -c 'from brain_core.layers import DATA_PATHS; print(" ".join(DATA_PATHS))')"
for p in roles/ doctrine/ teams/ MEMORY.md runtime/ config/; do
  case " $paths " in
    *" $p "*) echo "FAILED: системный путь $p в списке автокоммита"; exit 1;;
  esac
done
echo "OK: системные пути вне списка"

# ── 3. Хук отклоняет агентский коммит системного файла в главной ветке ──
guard="$PROJECT_ROOT/runtime/hooks/pre-commit-system-guard"
[ -x "$guard" ] || { echo "FAILED: нет хука $guard"; exit 1; }

# Операторская сессия задаётся явно: у оператора она может лежать в живом
# XDG_RUNTIME_DIR, и тогда кейс проверял бы его машину, а не хук.
session="$BRAIN_FACTORY_TMP/operator-session"
export BRAIN_OPERATOR_SESSION="$session"
rm -f "$session"

git add roles/developer.md
set +e
out="$(BRAIN_AGENT_ID=smoke-agent BRAIN_TASK_ID=t-smoke "$guard" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: хук пропустил правку системы агентом"; exit 1; }
grep -q "agent/t-smoke" <<< "$out" || {
  echo "FAILED: хук не назвал ветку задачи:"
  echo "$out"
  exit 1
}
echo "OK: агентский коммит системного файла в главной ветке отклонён"

# ── 4. В ветке задачи тот же коммит проходит ──
git switch -q -c agent/t-smoke
set +e
BRAIN_AGENT_ID=smoke-agent BRAIN_TASK_ID=t-smoke "$guard" >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: хук отклонил правку в ветке задачи"; exit 1; }
echo "OK: в ветке agent/<task-id> правка проходит"

# ── 5. Неопознанный процесс отклоняется так же, как назвавшийся агент ──
# Это воспроизведение обхода 14–15 августа 2026: раньше признаком человека
# служило ОТСУТСТВИЕ BRAIN_AGENT_ID, поэтому агент, её не выставивший, писал в
# системный слой master свободно. Вывод хука уводится в переменную: и stdout, и
# stderr тогда — каналы, а не терминал, и опознание детерминировано вне
# зависимости от того, из терминала ли запущен сам сьют.
git switch -q master 2>/dev/null || git switch -q main
set +e
out="$(env -u BRAIN_AGENT_ID -u BRAIN_TASK_ID "$guard" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || {
  echo "FAILED: коммит системного файла без BRAIN_AGENT_ID прошёл — обход открыт"
  exit 1
}
grep -q "неопознанный процесс" <<< "$out" || {
  echo "FAILED: хук не назвал причину отказа:"; echo "$out"; exit 1;
}
grep -q "roles/developer.md" <<< "$out" || {
  echo "FAILED: хук не перечислил системные файлы:"; echo "$out"; exit 1;
}
echo "OK: без опознания системный файл в главной ветке не проходит"

# ── 6. Оператор со свежей сессией проходит ──
: > "$session"
set +e
env -u BRAIN_AGENT_ID "$guard" >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: хук мешает опознанному оператору"; exit 1; }
echo "OK: свежая операторская сессия пропускает правку"

# ── 7. Протухшая сессия человеком не считается ──
touch -d '-1 hour' "$session"
set +e
out="$(env -u BRAIN_AGENT_ID "$guard" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: протухшая сессия всё ещё пропускает"; exit 1; }
grep -q "истекла" <<< "$out" || { echo "FAILED: не сказано, что сессия истекла"; echo "$out"; exit 1; }
rm -f "$session"
echo "OK: протухшая сессия отклоняется"

# ── 8. Интерактивный терминал опознаёт человека сам ──
if command -v script >/dev/null 2>&1; then
  probe="$BRAIN_FACTORY_TMP/tty-probe.sh"
  cat > "$probe" <<EOF
#!/usr/bin/env bash
cd "$BRAIN_PATH"
env -u BRAIN_AGENT_ID BRAIN_OPERATOR_SESSION="$BRAIN_FACTORY_TMP/нет-сессии" "$guard"
echo "TTYRC=\$?"
EOF
  chmod +x "$probe"
  tty_out="$(script -qec "$probe" /dev/null 2>/dev/null || true)"
  grep -q "TTYRC=0" <<< "$tty_out" || {
    echo "FAILED: коммит из терминала не опознан как человеческий:"
    echo "$tty_out"
    exit 1
  }
  echo "OK: коммит из интерактивного терминала проходит"
else
  echo "SKIP: нет утилиты script — проверка терминала пропущена"
fi

# ── 9. Осечка самой проверки — отказ, а не тихий пропуск ──
mkdir -p "$BRAIN_FACTORY_TMP/nopython"
printf '#!/bin/sh\nexit 127\n' > "$BRAIN_FACTORY_TMP/nopython/python3"
chmod +x "$BRAIN_FACTORY_TMP/nopython/python3"
set +e
out="$(env -u BRAIN_AGENT_ID PATH="$BRAIN_FACTORY_TMP/nopython:$PATH" "$guard" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: без работающего python3 хук пропустил коммит"; exit 1; }
grep -q "не смог проверить" <<< "$out" || {
  echo "FAILED: непонятная причина отказа при осечке:"; echo "$out"; exit 1;
}
echo "OK: неисполнимая проверка отклоняет коммит"

echo ">>> autocommit scope checks passed"
