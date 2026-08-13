#!/usr/bin/env bash
# case: publish-optin — страница wiki публикуется только с явной пометкой
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying wiki pages are published opt-in only"

pub="$PROJECT_ROOT/runtime/bin/brain-publish"
[ -x "$pub" ] || { echo "FAILED: brain-publish not executable"; exit 1; }

# Проверяем саму логику отбора, не запуская полную сборку: она требует
# файла секретов и git-дерева исходников.
grep -q "is_public_page" "$pub" || { echo "FAILED: opt-in check missing"; exit 1; }
grep -q "visibility:\[\[:space:\]\]\*public" "$pub" || {
    echo "FAILED: visibility marker not required"; exit 1;
}
grep -q "is_public_page \"\$rel\" || return 0" "$pub" || {
    echo "FAILED: copy_one does not consult the opt-in check"; exit 1;
}
echo "OK: publish consults an explicit visibility marker"

# Пометка есть у тех страниц, что действительно публикуются.
marked=$(grep -l '^visibility: public' "$PROJECT_ROOT"/wiki/*.md 2>/dev/null | wc -l | tr -d ' ')
[ "$marked" -ge 20 ] || {
    echo "FAILED: only $marked pages marked public — set looks broken"; exit 1;
}
echo "OK: $marked pages carry the public marker"

# Денилист по-прежнему сильнее пометки: клиентские семейства не публикуются
# даже если кто-то поставит visibility вручную.
grep -q 'wiki/projects-\*' "$pub" || { echo "FAILED: project pages not denied"; exit 1; }
echo "OK: client page families stay denied"

echo ">>> publish opt-in checks passed"
