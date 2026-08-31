#!/usr/bin/env bash
# case: reinstall-cli — установленный CLI совпадает с деревом, stale .pth не живёт
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying reinstall replaces stale CLI and leftover runtime .pth"

brain_factory
unset BRAIN_SYSTEM_PATH BRAIN_ENV_FILE
# Смоук выставляет PYTHONPATH на дерево раннера. Проверяем установку как
# оператор: только ~/.local/bin + user-site .pth, без подсказки из обвязки.
unset PYTHONPATH

REAL_PYTHON="$(command -v python3)"

install_fake_pip_success() {
  # На живом Homebrew pip --user падает из-за PEP 668, и текущий setup
  # пишет .pth только в ветке отказа. Баг «успешный pip оставляет чужой
  # .pth» на этой машине не проявляется, пока pip не начнёт проходить.
  mkdir -p "$HOME/bin"
  cat > "$HOME/bin/python3" <<EOF
#!/usr/bin/env bash
if [ "\${1:-}" = "-m" ] && [ "\${2:-}" = "pip" ]; then
  exit 0
fi
exec "$REAL_PYTHON" "\$@"
EOF
  chmod +x "$HOME/bin/python3"
  export PATH="$HOME/bin:$PATH"
}

pth_path() {
  "$REAL_PYTHON" - <<'PY'
import site
from pathlib import Path
print(Path(site.getusersitepackages()) / "brain-runtime.pth")
PY
}

plant_stale_pth() {
  local stale_lib="$1"
  mkdir -p "$stale_lib"
  "$REAL_PYTHON" - "$stale_lib" <<'PY'
import site
import sys
from pathlib import Path

target = Path(site.getusersitepackages())
target.mkdir(parents=True, exist_ok=True)
(target / "brain-runtime.pth").write_text(sys.argv[1] + "\n", encoding="utf-8")
print(target / "brain-runtime.pth")
PY
}

assert_pth_points_at() {
  local expected_lib="$1"
  local stale_lib="$2"
  local pth
  pth="$(pth_path)"
  [ -f "$pth" ] || { echo "FAILED: brain-runtime.pth не записан"; exit 1; }
  grep -F "$stale_lib" "$pth" >/dev/null && {
    echo "FAILED: .pth всё ещё указывает на stale-чекаут: $(cat "$pth")"
    exit 1
  }
  grep -F "$expected_lib" "$pth" >/dev/null || {
    echo "FAILED: .pth не указывает на текущее дерево: $(cat "$pth")"
    exit 1
  }
  echo "OK: .pth переписан на $expected_lib"
}

assert_status_clean() {
  local stale_lib="$1"
  local status_txt
  status_txt="$(env -u PYTHONPATH brain-status 2>&1 || true)"
  grep -F "$stale_lib" <<< "$status_txt" >/dev/null && {
    echo "FAILED: brain-status ссылается на stale-чекаут"
    echo "$status_txt"
    exit 1
  }
  grep -q "^Core: " <<< "$status_txt" || {
    echo "FAILED: brain-status не напечатал Core:"
    echo "$status_txt"
    exit 1
  }
  grep -q "unpackaged" <<< "$status_txt" && {
    echo "FAILED: brain-status всё ещё говорит unpackaged"
    echo "$status_txt"
    exit 1
  }
  grep -E "site-packages|brain-runtime.pth" <<< "$status_txt" >/dev/null || {
    echo "FAILED: brain-status не показал путь установки (site-packages или .pth)"
    echo "$status_txt"
    exit 1
  }
  echo "OK: brain-status не unpackaged и не ссылается на stale-чекаут"
}

copy_system_tree() {
  local dest="$1"
  mkdir -p "$dest"
  cp "$PROJECT_ROOT/setup-brain-v2.sh" "$dest/"
  cp "$PROJECT_ROOT/install-brain-mcp.sh" "$dest/"
  cp "$PROJECT_ROOT/pyproject.toml" "$dest/"
  cp -R "$PROJECT_ROOT/runtime" "$dest/"
  cp -R "$PROJECT_ROOT/roles" "$dest/"
  cp -R "$PROJECT_ROOT/teams" "$dest/"
  cp -R "$PROJECT_ROOT/doctrine" "$dest/"
  cp -R "$PROJECT_ROOT/skills" "$dest/"
  cp -R "$PROJECT_ROOT/config" "$dest/"
}

install_fake_pip_success

# Имитируем живой контур: старый wrapper всё ещё прокидывает --client,
# а .pth указывает на чужой чекаут. Именно так падал ~/.local/bin/brain-task.
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/brain-task" <<'STALE'
#!/usr/bin/env bash
set -eu
# stale: always forward --client, even when the user did not pass it
python3 -m brain_app.queue list --client "$@"
STALE
chmod +x "$HOME/.local/bin/brain-task"

stale_lib="$HOME/Документы/Brain/files/runtime/lib"
plant_stale_pth "$stale_lib"

echo ">>> setup from runner tree with successful pip must rewrite .pth"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

cmp -s "$PROJECT_ROOT/runtime/bin/brain-task" "$HOME/.local/bin/brain-task" || {
  echo "FAILED: установленный brain-task не совпал с деревом"
  exit 1
}

set +e
list_out="$(env -u PYTHONPATH brain-task list 2>&1)"
list_rc=$?
set -e
grep -q "unrecognized arguments: --client" <<< "$list_out" && {
  echo "FAILED: brain-task list всё ещё прокидывает --client"
  echo "$list_out"
  exit 1
}
[ "$list_rc" -eq 0 ] || {
  echo "FAILED: brain-task list без аргументов упал (rc=$list_rc)"
  echo "$list_out"
  exit 1
}
echo "OK: brain-task list без аргументов не падает"

reject_client() {
  local label="$1"; shift
  set +e
  local out rc
  out="$(env -u PYTHONPATH "$@" 2>&1)"
  rc=$?
  set -e
  [ "$rc" -eq 2 ] || {
    echo "FAILED: $label rc=$rc (ждали 2)"
    echo "$out"
    exit 1
  }
  grep -q "снят" <<< "$out" || {
    echo "FAILED: $label не напечатал отказ"
    echo "$out"
    exit 1
  }
}

# Top-level `brain-task --client` is an unknown command (usage, rc=1).
# The stale wrapper bug was on list/next: they forwarded --client always.
reject_client "brain-task list --client" brain-task list --client foo
reject_client "brain-task next --client" brain-task next --client foo
echo "OK: --client печатает отказ и выходит 2"

assert_pth_points_at "$PROJECT_ROOT/runtime/lib" "$stale_lib"
assert_status_clean "$stale_lib"

# Повторный setup не меняет установленные команды и .pth.
pth="$(pth_path)"
before_hash="$(cksum "$HOME/.local/bin/brain-task" "$HOME/.local/bin/brain-status" "$pth")"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1
after_hash="$(cksum "$HOME/.local/bin/brain-task" "$HOME/.local/bin/brain-status" "$pth")"
[ "$before_hash" = "$after_hash" ] || {
  echo "FAILED: повторный setup не идемпотентен"
  echo "before: $before_hash"
  echo "after:  $after_hash"
  exit 1
}
echo "OK: повторный setup идемпотентен"

echo ">>> split-root setup with successful pip rewrites .pth onto the system tree"
split_data="$BRAIN_FACTORY_TMP/split-data"
split_system="$BRAIN_FACTORY_TMP/split-system"
mkdir -p "$split_data/wiki" "$split_data/tasks" "$split_data/raw" "$split_data/council" "$split_data/.locks"
printf '# private\n' > "$split_data/MEMORY.md"
printf '# Active\n' > "$split_data/tasks/active.md"
printf '# Done\n' > "$split_data/tasks/done.md"
printf '# Index\n' > "$split_data/wiki/index.md"
printf '# Log\n' > "$split_data/wiki/log.md"
copy_system_tree "$split_system"

plant_stale_pth "$stale_lib"
export BRAIN_PATH="$split_data"
export BRAIN_SYSTEM_PATH="$split_system"
bash "$split_system/setup-brain-v2.sh" >/dev/null 2>&1
assert_pth_points_at "$split_system/runtime/lib" "$stale_lib"
assert_status_clean "$stale_lib"
echo "OK: split-root .pth points at system runtime/lib"

echo ">>> legacy single-root setup with successful pip rewrites .pth onto that tree"
legacy="$BRAIN_FACTORY_TMP/legacy-root"
copy_system_tree "$legacy"
plant_stale_pth "$stale_lib"
unset BRAIN_SYSTEM_PATH
export BRAIN_PATH="$legacy"
bash "$legacy/setup-brain-v2.sh" >/dev/null 2>&1
assert_pth_points_at "$legacy/runtime/lib" "$stale_lib"
assert_status_clean "$stale_lib"
echo "OK: legacy single-root .pth points at that tree's runtime/lib"

echo ">>> pip-failure path still rewrites .pth (PEP 668)"
cat > "$HOME/bin/python3" <<EOF
#!/usr/bin/env bash
if [ "\${1:-}" = "-m" ] && [ "\${2:-}" = "pip" ]; then
  echo "fake-pip: fail" >&2
  exit 1
fi
exec "$REAL_PYTHON" "\$@"
EOF
chmod +x "$HOME/bin/python3"
plant_stale_pth "$stale_lib"
unset BRAIN_SYSTEM_PATH
export BRAIN_PATH="$BRAIN_FACTORY_TMP/brain"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1
assert_pth_points_at "$PROJECT_ROOT/runtime/lib" "$stale_lib"
assert_status_clean "$stale_lib"
echo "OK: pip-failure still rewrites .pth"

echo ">>> reinstall-cli checks passed"
