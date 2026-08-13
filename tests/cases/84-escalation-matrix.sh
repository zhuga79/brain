#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying machine-readable escalation matrix"

# 1. Repo source of truth: doctrine/escalation-matrix.yaml exists, parses, and
#    every primary/escalate role references an existing repo roles/*.md.
python3 - <<'PYEOF'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["PROJECT_ROOT"] + "/runtime/lib")
from brain_wiki.escalation import load_escalation_matrix

repo = Path(os.environ["PROJECT_ROOT"])
data, errors = load_escalation_matrix(repo)
assert not errors, "repo escalation matrix errors:\n" + "\n".join(errors)
assert data, "repo escalation matrix missing"

known = {p.stem for p in (repo / "roles").glob("*.md")}
missing = []
for section in ("zones", "tax_stages"):
    for entry in data.get(section, []):
        label = f"{section}/{entry.get('id', '?')}"
        for role in entry.get("primary", []):
            if role not in known:
                missing.append(f"{label}: primary {role}")
        for role in entry.get("escalate", []):
            if role not in known:
                missing.append(f"{label}: escalate {role}")
assert not missing, "repo matrix references unknown roles:\n" + "\n".join(missing)
print(f"repo matrix OK ({len(data['zones'])} zones, {len(data['tax_stages'])} tax stages)")
PYEOF

# 2. Factory brain: setup-brain-v2.sh installs the matrix and brain-validate
#    is clean on the factory.
[ -f "$BRAIN_PATH/doctrine/escalation-matrix.yaml" ] || {
    echo "FAILED: setup did not install doctrine/escalation-matrix.yaml"
    exit 1
}
# Кейс отвечает за матрицу эскалаций, а не за здоровье общей фабрики: другие
# кейсы правят её роли и конфигурацию, и падение brain-validate по их причинам
# раньше убивало этот кейс молча, через set -e.
set +e
brain-validate > /tmp/brain_validate_esc_clean.log 2>&1
set -e
if grep -qiE "escalation|эскалац" /tmp/brain_validate_esc_clean.log; then
    echo "FAILED: brain-validate жалуется на матрицу эскалаций на чистой фабрике"
    grep -iE "escalation|эскалац" /tmp/brain_validate_esc_clean.log
    exit 1
fi

# 3. Missing matrix file → brain-validate fails with a clear error.
BACKUP_ESC_YAML="$(mktemp)"
cp "$BRAIN_PATH/doctrine/escalation-matrix.yaml" "$BACKUP_ESC_YAML"
restore_yaml() {
    [ -f "$BACKUP_ESC_YAML" ] && mv -f "$BACKUP_ESC_YAML" \
        "$BRAIN_PATH/doctrine/escalation-matrix.yaml"
}
trap restore_yaml EXIT

rm -f "$BRAIN_PATH/doctrine/escalation-matrix.yaml"
set +e
brain-validate > /tmp/brain_validate_esc_missing.log 2>&1
missing_exit=$?
set -e
[ "$missing_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on missing escalation matrix"; exit 1; }
grep -q "нет файла" /tmp/brain_validate_esc_missing.log || {
    echo "FAILED: missing-matrix error not reported"
    cat /tmp/brain_validate_esc_missing.log
    exit 1
}

# Возвращаем файл сразу: следующий шаг его правит, а восстановление по trap
# случится только на выходе — до него шаг падал на отсутствующем файле.
cp "$BACKUP_ESC_YAML" "$BRAIN_PATH/doctrine/escalation-matrix.yaml"

# 4. Zone referencing a non-existent primary role → brain-validate fails.
python3 - "$BRAIN_PATH/doctrine/escalation-matrix.yaml" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("primary: [lawyer]", "primary: [ghost-role]", 1)
path.write_text(text, encoding="utf-8")
PYEOF
set +e
brain-validate > /tmp/brain_validate_esc_ghost.log 2>&1
ghost_exit=$?
set -e
[ "$ghost_exit" -ne 0 ] || { echo "FAILED: brain-validate should fail on ghost primary role"; exit 1; }
grep -q "primary-роль 'ghost-role'" /tmp/brain_validate_esc_ghost.log || {
    echo "FAILED: ghost-role error not reported"
    cat /tmp/brain_validate_esc_ghost.log
    exit 1
}

restore_yaml
trap - EXIT
rm -f "$BACKUP_ESC_YAML"

echo "escalation matrix validation OK"
