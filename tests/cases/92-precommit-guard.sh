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

# ── 3. Записи системы дописываются свободно ──
# Журнал и архив несут имена по существу и дописываются самой системой при
# каждой операции. Если гейт смотрит на них, очередь встаёт.
mkdir -p "$BRAIN_PATH/tasks"
printf 'Дело Одуванчикова: задача закрыта.\n' >> "$BRAIN_PATH/wiki/log.md"
printf -- '- [x] [P1] t-проба — Дело Одуванчикова\n' >> "$BRAIN_PATH/tasks/done.md"
git add wiki/log.md tasks/done.md
git commit --quiet -m "запись в журнал" || {
  echo "FAILED: гейт заблокировал дописывание журнала — система не сможет работать"
  exit 1
}
echo "OK: журнал и архив дописываются"

# ── 4. Без файла секретов хук не блокирует всё подряд ──
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

echo ">>> pre-commit guard checks passed"
