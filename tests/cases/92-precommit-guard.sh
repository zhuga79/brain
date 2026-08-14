#!/usr/bin/env bash
# case: precommit-guard — pre-commit не пускает документы дела в репозиторий системы
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying pre-commit blocks case documents entering the system repo"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

cd "$BRAIN_PATH"
git init --quiet 2>/dev/null || true
git config user.email "case@example.invalid"
git config user.name "case"

# Установщик хуков зашит на свой PROJECT_ROOT, поэтому в песочнице ставим хук
# из того же исходника, но с корнем песочницы.
sed "s|^PROJECT_ROOT=.*|PROJECT_ROOT=\"$BRAIN_PATH\"|" \
    "$PROJECT_ROOT/install-hooks.sh" > "$BRAIN_FACTORY_TMP/install-hooks.sh"
mkdir -p "$BRAIN_PATH/runtime/bin"
cp "$PROJECT_ROOT/runtime/bin/brain-guard" "$BRAIN_PATH/runtime/bin/"
mkdir -p "$BRAIN_PATH/tests/python"
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"

# Базовый коммит до установки хука: в свежей песочнице ещё ничего не
# отслеживается, и журнал, созданный установщиком, считался бы новым файлом.
git add -A >/dev/null 2>&1
git commit --quiet -m "базовое состояние песочницы" >/dev/null 2>&1 || true

bash "$BRAIN_FACTORY_TMP/install-hooks.sh" >/dev/null 2>&1

hook="$BRAIN_PATH/.git/hooks/pre-commit"
[ -x "$hook" ] || { echo "FAILED: хук не установлен"; exit 1; }
grep -q "brain-guard" "$hook" || { echo "FAILED: в хуке нет вызова brain-guard"; exit 1; }
echo "OK: хук зовёт brain-guard"

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

# ── 3. Smoke gate blocks the commit ──
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
echo "smoke failed" >&2
exit 1
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"
printf -- '---\ntitle: smoke-probe\ntype: concept\n---\n\nprobe\n' > "$BRAIN_PATH/wiki/precommit-smoke.md"
git add tests/run.sh wiki/precommit-smoke.md

set +e
out="$(git commit -m "smoke fails" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: commit passed despite failing smoke"; exit 1; }
grep -q "Running smoke suite" <<< "$out" || { echo "FAILED: hook did not run smoke suite"; echo "$out"; exit 1; }
grep -q "smoke failed" <<< "$out" || { echo "FAILED: smoke failure not surfaced"; echo "$out"; exit 1; }
echo "OK: failing smoke blocks the commit"

# ── 4. Pytest gate blocks the commit ──
cat > "$BRAIN_PATH/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BRAIN_PATH/tests/run.sh"
cat > "$BRAIN_PATH/tests/python/test_fail_gate.py" <<'EOF'
def test_fails():
    assert False
EOF
git add tests/run.sh tests/python/test_fail_gate.py

set +e
out="$(git commit -m "pytest fails" 2>&1)"
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAILED: commit passed despite failing pytest"; exit 1; }
grep -q "Running unit tests (pytest)" <<< "$out" || { echo "FAILED: hook did not run pytest"; echo "$out"; exit 1; }
grep -Eq "FAILED|AssertionError" <<< "$out" || { echo "FAILED: pytest failure not surfaced"; echo "$out"; exit 1; }
echo "OK: failing pytest blocks the commit"

# ── 5. Без файла секретов хук не блокирует всё подряд ──
# Свежий клон не имеет именного списка; fail-closed в этой точке означал бы,
# что коммитить нельзя вообще ничего.
rm -f "$BRAIN_PATH/.publish-secrets.local"
git rm --quiet --cached tests/python/test_fail_gate.py
rm -f "$BRAIN_PATH/tests/python/test_fail_gate.py"
rm -rf "$BRAIN_PATH/tests/python/__pycache__"
cat > "$BRAIN_PATH/tests/python/test_pass_gate.py" <<'EOF'
def test_passes():
    assert True
EOF
printf -- '---\ntitle: Ещё\ntype: concept\n---\n\nЕщё одна страница подсистемы.\n' \
    > "$BRAIN_PATH/wiki/proba-bez-spiska.md"
git add tests/python/test_pass_gate.py wiki/proba-bez-spiska.md
git commit --quiet -m "без списка секретов" || {
  echo "FAILED: без файла секретов хук заблокировал обычный коммит"
  exit 1
}
echo "OK: без именного списка хук не блокирует обычный коммит"

echo ">>> pre-commit guard checks passed"
