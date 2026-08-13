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

# ── 5. Для человека хук молчит ──
git switch -q master 2>/dev/null || git switch -q main
set +e
"$guard" >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: хук мешает человеку"; exit 1; }
echo "OK: без BRAIN_AGENT_ID хук не вмешивается"

echo ">>> autocommit scope checks passed"
