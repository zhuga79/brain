#!/usr/bin/env bash
# case: retire-publish — снапшот и денилист уходят вместе с инверсией
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-publish and the denylist are gone"

[ ! -e "$PROJECT_ROOT/runtime/bin/brain-publish" ] || {
  echo "FAILED: runtime/bin/brain-publish still exists"
  exit 1
}
[ ! -e "$HOME/.local/bin/brain-publish" ] || {
  echo "FAILED: setup left brain-publish in $HOME/.local/bin"
  exit 1
}
echo "OK: brain-publish binary is gone"

if grep -RInE 'DENY_GLOBS|ALLOW_GLOBS|is_public_page|is_denied' \
     "$PROJECT_ROOT/runtime" --include='*.sh' --include='*.py' >/tmp/retire-deny.hits 2>/dev/null; then
  echo "FAILED: publish denylist helpers remain in runtime:"
  cat /tmp/retire-deny.hits
  exit 1
fi
echo "OK: denylist helpers are gone from runtime"

echo ">>> Verifying no leftover operational references"

python3 - "$PROJECT_ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
skip_dirs = {
    ".git", ".brain", "wiki", "tasks", "handoff", "council", "raw", "prd",
    "__pycache__", ".locks", "learning",
}
skip_files = {
    "docs/decisions/decision-public-source-of-truth.md",
    "docs/decisions/decision-post-inversion-cycle.md",
    "tests/cases/80-retire-publish.sh",
}
needles = (
    "brain-publish",
    "денилист",
    "DENY_GLOBS",
    "issue ценнее PR",
)
hits = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    if any(part in skip_dirs for part in path.relative_to(root).parts):
        continue
    if rel in skip_files:
        continue
    if path.suffix.lower() not in {".md", ".sh", ".py", ".txt", ".yml", ".yaml", ".json", ""}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for needle in needles:
        if needle in text:
            hits.append(f"{rel}: {needle}")

if hits:
    print("FAILED: leftover publish/denylist references:")
    print("\n".join(hits))
    sys.exit(1)
print("OK: operational code and docs no longer mention publish/denylist")
PY

echo ">>> Verifying CONTRIBUTING describes the ADR contribution lifecycle"

contrib="$PROJECT_ROOT/CONTRIBUTING.md"
[ -f "$contrib" ] || { echo "FAILED: CONTRIBUTING.md missing"; exit 1; }
grep -q 'issue ценнее PR' "$contrib" && {
  echo "FAILED: CONTRIBUTING still says «issue ценнее PR»"
  exit 1
}
for step in \
  '1. **Issue.**' \
  '2. **ADR вперёд кода.**' \
  '3. **PR.**' \
  '4. **CI.**' \
  '5. **Ревью.**' \
  '6. **Merge.**' \
  '7. **Приём в рабочее дерево.**'
do
  grep -Fq "$step" "$contrib" || {
    echo "FAILED: CONTRIBUTING missing ADR step: $step"
    exit 1
  }
done
grep -q 'Author' "$contrib" || {
  echo "FAILED: CONTRIBUTING does not say where authorship is kept"
  exit 1
}
grep -qi 'squash' "$contrib" || {
  echo "FAILED: CONTRIBUTING does not explain why squash is off"
  exit 1
}
echo "OK: CONTRIBUTING has ADR steps 1–7, authorship and squash rule"

echo ">>> Verifying README describes two repositories and install order"

readme="$PROJECT_ROOT/README.md"
[ -f "$readme" ] || { echo "FAILED: README.md missing"; exit 1; }
grep -qiE 'дву(х|мя) репозитор|два репозитор' "$readme" || {
  echo "FAILED: README does not describe two repositories"
  exit 1
}
grep -q 'BRAIN_PATH' "$readme" || {
  echo "FAILED: README missing BRAIN_PATH"
  exit 1
}
grep -q 'BRAIN_SYSTEM_PATH' "$readme" || {
  echo "FAILED: README missing BRAIN_SYSTEM_PATH"
  exit 1
}
grep -q 'setup-brain-v2.sh' "$readme" || {
  echo "FAILED: README missing setup-brain-v2.sh"
  exit 1
}
python3 - "$readme" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
setup_at = text.find("setup-brain-v2.sh")
sys_at = text.find("BRAIN_SYSTEM_PATH")
data_at = text.find("BRAIN_PATH")
if min(setup_at, sys_at, data_at) < 0:
    raise SystemExit("FAILED: README install pieces missing")
# Порядок установки: чекаут/setup системы, затем корни данных и системы.
if setup_at > sys_at:
    raise SystemExit("FAILED: README install order puts env before setup")
print("OK: README install order is setup then roots")
PY

echo ">>> Verifying brain-ops update does pull + install + tests"

ops="$PROJECT_ROOT/runtime/bin/brain-ops"
[ -x "$ops" ] || { echo "FAILED: brain-ops missing"; exit 1; }
ops_usage="$("$ops" 2>&1 || true)"
printf '%s\n' "$ops_usage" | grep -q update || {
  echo "FAILED: brain-ops usage does not mention update"
  echo "$ops_usage"
  exit 1
}

brain_factory
git config --global user.email "case@example.com"
git config --global user.name "case"
td="$BRAIN_FACTORY_TMP"
sys="$td/system"
mkdir -p "$sys/tests" "$td/bin"
cat > "$sys/setup-brain-v2.sh" <<'EOF'
#!/usr/bin/env bash
echo install >> "$HOME/update-steps.txt"
EOF
chmod +x "$sys/setup-brain-v2.sh"
cat > "$sys/tests/run.sh" <<'EOF'
#!/usr/bin/env bash
echo tests >> "$HOME/update-steps.txt"
EOF
chmod +x "$sys/tests/run.sh"
# Real (if throwaway) git repo with a configured upstream — brain-ops update
# now checks tracking before it ever calls `pull`, so a bare `.git/` stub
# with no branch/remote would trip that check before reaching the stub below.
git -C "$sys" init -q
git -C "$sys" add -A
git -C "$sys" commit -q -m init
sys_remote="$td/system-remote.git"
git init --bare -q "$sys_remote"
git -C "$sys" remote add origin "$sys_remote"
git -C "$sys" push -q -u origin HEAD
cat > "$td/bin/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >> "$HOME/update-git.txt"
# Only short-circuit `pull`; every other subcommand (including the upstream
# checks brain-ops now runs first) must still see the original arguments —
# in particular `-C <dir>` — or it silently falls back to the caller's cwd.
sub="$1"
if [ "$sub" = "-C" ]; then
  sub="$3"
fi
if [ "$sub" = "pull" ]; then
  echo pulled >> "$HOME/update-steps.txt"
  exit 0
fi
exec /usr/bin/git "$@"
EOF
chmod +x "$td/bin/git"

export BRAIN_SYSTEM_PATH="$sys"
export PATH="$td/bin:$PATH"
: > "$HOME/update-steps.txt"
"$ops" update
got="$(tr '\n' ' ' < "$HOME/update-steps.txt" | sed 's/[[:space:]]*$//')"
[ "$got" = "pulled install tests" ] || {
  echo "FAILED: brain-ops update steps were '$got', expected 'pulled install tests'"
  echo "git log:"; cat "$HOME/update-git.txt" 2>/dev/null || true
  exit 1
}
echo "OK: brain-ops update runs pull, then install, then tests"

echo ">>> Verifying fate of t-2026-08-10-wiki-opt-in-glob is recorded"

adr="$PROJECT_ROOT/docs/decisions/decision-public-source-of-truth.md"
donef="$PROJECT_ROOT/tasks/done.md"
grep -q 't-2026-08-10-wiki-opt-in-glob' "$adr" "$donef" || {
  echo "FAILED: wiki-opt-in-glob is not mentioned after retirement"
  exit 1
}
grep -Eiq 'промежуточн|interim' "$adr" "$donef" || {
  echo "FAILED: opt-in is not recorded as interim"
  exit 1
}
grep -Eiq 'структурн' "$adr" "$donef" || {
  echo "FAILED: structural boundary after the split is not recorded"
  exit 1
}
echo "OK: wiki-opt-in-glob fate is explicit (interim opt-in, structural boundary)"

echo ">>> retire-publish checks passed"
