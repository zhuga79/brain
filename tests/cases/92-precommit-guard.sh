#!/usr/bin/env bash
# case: precommit-guard — fast policy on commit, isolated suite on pre-push
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying pre-commit policy gate and pre-push suite gate"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

cd "$BRAIN_PATH"
git init --quiet -b main 2>/dev/null || git init --quiet
git config user.email "case@example.invalid"
git config user.name "case"

mkdir -p "$BRAIN_PATH/runtime/bin" "$BRAIN_PATH/runtime/hooks" "$BRAIN_PATH/runtime/lib" "$BRAIN_PATH/tests/python"
cp "$PROJECT_ROOT/runtime/bin/brain-guard" "$BRAIN_PATH/runtime/bin/"
chmod +x "$BRAIN_PATH/runtime/bin/brain-guard"
cp "$PROJECT_ROOT/runtime/hooks/pre-commit-system-guard" "$BRAIN_PATH/runtime/hooks/"
chmod +x "$BRAIN_PATH/runtime/hooks/pre-commit-system-guard"
cp -a "$PROJECT_ROOT/runtime/lib/brain_core" "$BRAIN_PATH/runtime/lib/"
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"

# Базовый коммит до установки хука: в свежей песочнице ещё ничего не
# отслеживается, и журнал, созданный установщиком, считался бы новым файлом.
git add -A >/dev/null 2>&1
git commit --quiet -m "базовое состояние песочницы" >/dev/null 2>&1 || true

# Установщик резолвит каталог хуков через git rev-parse в текущем чекауте.
bash "$PROJECT_ROOT/install-hooks.sh" >/dev/null 2>&1

hook="$BRAIN_PATH/.git/hooks/pre-commit"
push_hook="$BRAIN_PATH/.git/hooks/pre-push"
[ -x "$hook" ] || { echo "FAILED: pre-commit хук не установлен"; exit 1; }
[ -x "$push_hook" ] || { echo "FAILED: pre-push хук не установлен"; exit 1; }
grep -q "brain-guard" "$hook" || { echo "FAILED: в pre-commit нет вызова brain-guard"; exit 1; }
grep -q "tests/run.sh" "$hook" && { echo "FAILED: pre-commit всё ещё зовёт tests/run.sh"; exit 1; }
grep -qi "pytest" "$hook" && { echo "FAILED: pre-commit всё ещё зовёт pytest"; exit 1; }
grep -q "tests/run.sh" "$push_hook" || { echo "FAILED: pre-push не зовёт tests/run.sh"; exit 1; }
grep -qi "pytest" "$push_hook" || { echo "FAILED: pre-push не зовёт pytest"; exit 1; }
grep -q "env -i" "$push_hook" || { echo "FAILED: pre-push не строит env allowlist через env -i"; exit 1; }
echo "OK: хуки разделены — политика на commit, сьют на push"

git init --bare --quiet "$BRAIN_FACTORY_TMP/origin.git"
git remote add origin "$BRAIN_FACTORY_TMP/origin.git"

# ── 1. Именные правила есть → документ дела не проходит ──
cat > "$BRAIN_PATH/.publish-secrets.local" <<'SECRETS'
PII_PATTERN='Одуванчиков'
SECRETS

mkdir -p "$BRAIN_PATH/wiki"
printf -- '---\ntitle: Проба\ntype: concept\n---\n\nДело Одуванчикова: анализ.\n' \
    > "$BRAIN_PATH/wiki/proba-dela.md"
git add wiki/proba-dela.md

set +e
out="$(git commit -m "проба" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: коммит с документом дела прошёл"; echo "$out"; exit 1; }
grep -qi "guard\|персональн\|папка дела" <<< "$out" || {
  echo "FAILED: непонятная причина отказа"; echo "$out"; exit 1;
}
echo "OK: документ дела в wiki/ отклонён"

# ── 2. Системная страница проходит ──
git rm --quiet --cached wiki/proba-dela.md
rm -f "$BRAIN_PATH/wiki/proba-dela.md"
printf -- '---\ntitle: Обзор\ntype: concept\n---\n\nОписание подсистемы очереди.\n' \
    > "$BRAIN_PATH/wiki/proba-sistemy.md"
git add wiki/proba-sistemy.md
git commit --quiet -m "системная страница" || {
  echo "FAILED: системная страница не прошла хук"
  exit 1
}
echo "OK: системная страница проходит"

# ── 3. system-guard блокирует системный файл на главной ветке ──
mkdir -p "$BRAIN_PATH/roles"
printf -- '# probe\n' > "$BRAIN_PATH/roles/guard-probe.md"
git add roles/guard-probe.md
set +e
out="$(git commit -m "system layer" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: system-guard пропустил системный файл"; echo "$out"; exit 1; }
grep -qi "системн\|ОТКАЗ\|agent/" <<< "$out" || {
  echo "FAILED: отказ system-guard не похож на гейт"; echo "$out"; exit 1
}
echo "OK: system-guard блокирует коммит системного файла"
git rm --quiet --cached roles/guard-probe.md
rm -f "$BRAIN_PATH/roles/guard-probe.md"

# ── 4. Падающий smoke не блокирует commit, блокирует pre-push ──
# tests/run.sh — системный файл: правку в индекс не кладём (её бы отклонил
# system-guard, и это не то, что здесь проверяется). Хук pre-push читает
# рабочее дерево, поэтому падающий смоук достаточно положить в рабочее дерево,
# а коммитить — невинную страницу данных.
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
echo "smoke failed" >&2
exit 1
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"
printf -- '---\ntitle: smoke-probe\ntype: concept\n---\n\nprobe\n' > "$BRAIN_PATH/wiki/precommit-smoke.md"
git add wiki/precommit-smoke.md

set +e
out="$(git commit -m "smoke fails" 2>&1)"
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: падающий smoke блокирует commit"; echo "$out"; exit 1; }
grep -q "Running smoke suite" <<< "$out" && { echo "FAILED: pre-commit всё ещё гоняет smoke"; echo "$out"; exit 1; }
echo "OK: падающий smoke не блокирует commit"

set +e
out="$(git push origin HEAD 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: push прошёл при падающем smoke"; echo "$out"; exit 1; }
grep -q "smoke failed" <<< "$out" || { echo "FAILED: smoke failure не всплыл на pre-push"; echo "$out"; exit 1; }
echo "OK: падающий smoke блокирует pre-push"

# вернуть зелёный смоук для следующего шага
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"

# ── 5. Падающий pytest не блокирует commit, блокирует pre-push ──
cat > "$BRAIN_PATH/tests/python/test_fail_gate.py" <<'EOF'
def test_fails():
    assert False
EOF
printf -- '---\ntitle: pytest-probe\ntype: concept\n---\n\nprobe\n' > "$BRAIN_PATH/wiki/precommit-pytest.md"
git add wiki/precommit-pytest.md

set +e
out="$(git commit -m "pytest fails" 2>&1)"
rc=$?
set -e
[ "$rc" -eq 0 ] || { echo "FAILED: падающий pytest блокирует commit"; echo "$out"; exit 1; }
grep -q "Running unit tests (pytest)" <<< "$out" && { echo "FAILED: pre-commit всё ещё гоняет pytest"; echo "$out"; exit 1; }
echo "OK: падающий pytest не блокирует commit"

set +e
out="$(git push origin HEAD 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: push прошёл при падающем pytest"; echo "$out"; exit 1; }
grep -Eq "FAILED|AssertionError|pytest" <<< "$out" || { echo "FAILED: pytest failure не всплыл на pre-push"; echo "$out"; exit 1; }
echo "OK: падающий pytest блокирует pre-push"

rm -f "$BRAIN_PATH/tests/python/test_fail_gate.py"
rm -rf "$BRAIN_PATH/tests/python/__pycache__"

# ── 6. Без файла секретов хук не блокирует всё подряд ──
# Свежий клон не имеет именного списка; fail-closed в этой точке означал бы,
# что коммитить нельзя вообще ничего.
rm -f "$BRAIN_PATH/.publish-secrets.local"
printf -- '---\ntitle: Ещё\ntype: concept\n---\n\nЕщё одна страница подсистемы.\n' \
    > "$BRAIN_PATH/wiki/proba-bez-spiska.md"
git add wiki/proba-bez-spiska.md
git commit --quiet -m "без списка секретов" || {
  echo "FAILED: без файла секретов хук заблокировал обычный коммит"
  exit 1
}
echo "OK: без именного списка хук не блокирует обычный коммит"

echo ">>> pre-commit / pre-push gate checks passed"
