#!/usr/bin/env bash
# case: deb-build — runtime/packaging/build-deb.sh builds an installable
# brain-runtime_<version>_all.deb from the canonical tree, no fpm/debhelper,
# no ~/.local (federation PRD s5).
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying build-deb.sh"

command -v dpkg-deb >/dev/null 2>&1 || { echo "SKIP: dpkg-deb not available"; exit 0; }
command -v fakeroot >/dev/null 2>&1 || { echo "SKIP: fakeroot not available"; exit 0; }

work="$(mktemp -d)"
ALL_TMPDIRS+=("$work")
script="$PROJECT_ROOT/runtime/packaging/build-deb.sh"
[ -x "$script" ] || { echo "FAILED: $script missing or not executable"; exit 1; }

# build-deb.sh must not reach into an installed tree
grep -qE '(^|[^A-Za-z._-])~?/?\.local/|\$HOME/\.local' "$script" \
  && { echo "FAILED: build-deb.sh references ~/.local"; exit 1; }

version="$(sed -nE 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$PROJECT_ROOT/pyproject.toml" | head -1)"
[ -n "$version" ] || { echo "FAILED: no version in pyproject.toml"; exit 1; }

bash "$script" --out-dir "$work/dist" > "$work/build.log" 2>&1 || {
  echo "FAILED: build-deb.sh exited non-zero"; cat "$work/build.log"; exit 1;
}
deb="$work/dist/brain-runtime_${version}_all.deb"
[ -f "$deb" ] || { echo "FAILED: expected $deb"; ls -la "$work/dist"; exit 1; }

# --- control fields ---
fld() { dpkg-deb --field "$deb" "$1"; }
[ "$(fld Package)" = "brain-runtime" ]        || { echo "FAILED: Package = $(fld Package)"; exit 1; }
[ "$(fld Version)" = "$version" ]             || { echo "FAILED: Version = $(fld Version), want $version"; exit 1; }
[ "$(fld Architecture)" = "all" ]             || { echo "FAILED: Architecture = $(fld Architecture)"; exit 1; }
case "$(fld Depends)" in
  *"python3 (>= 3.10)"*", git"*", jq"*) : ;;
  *) echo "FAILED: Depends = $(fld Depends)"; exit 1 ;;
esac
echo "$(fld Depends)" | grep -q 'misc:Depends' && { echo "FAILED: unresolved \${misc:Depends} in control"; exit 1; }

# --- FHS payload layout ---
contents="$(dpkg-deb --contents "$deb")"
for want in \
  './usr/bin/brain-task' \
  './usr/bin/brain-federation' \
  './usr/lib/python3/dist-packages/brain_core/version.py' \
  './usr/lib/python3/dist-packages/brain_task_parser.py' \
  './usr/share/brain/runtime/bin/brain-common' \
  './usr/share/brain/runtime/mcp/server.py' \
  './usr/share/brain/runtime/templates/v2/MEMORY.md' \
  './usr/share/brain/setup-brain-v2.sh' \
  './usr/share/brain/prd/_TEMPLATE.md' \
  './usr/share/brain/spec/' ; do
  echo "$contents" | grep -qE " ${want}\$| ${want} -> " \
    || { echo "FAILED: $want not in the package"; echo "$contents" | head -50; exit 1; }
done
# brain-common is a sourced library, never a /usr/bin entry point
echo "$contents" | grep -qE ' \./usr/bin/brain-common$' && { echo "FAILED: brain-common got a /usr/bin wrapper"; exit 1; }
# the importable library lives only in dist-packages, not under /usr/share
echo "$contents" | grep -qE ' \./usr/share/brain/runtime/lib/' && { echo "FAILED: runtime/lib duplicated under /usr/share/brain"; exit 1; }

# --- wrapper shape ---
dpkg-deb -x "$deb" "$work/x"
wrapper="$work/x/usr/bin/brain-task"
grep -q 'exec "/usr/share/brain/runtime/bin/brain-task"' "$wrapper" \
  || { echo "FAILED: wrapper does not exec the real path"; cat "$wrapper"; exit 1; }

# --- the packaged tree actually runs (dist-packages is on the default path
#     in a real Debian install; simulate that here) ---
out="$(PYTHONPATH="$work/x/usr/lib/python3/dist-packages:$work/x/usr/share/brain/runtime/mcp" \
  bash "$work/x/usr/share/brain/runtime/bin/brain-task" --help 2>&1 || true)"
echo "$out" | grep -q "brain-task" || { echo "FAILED: packaged brain-task --help produced no help"; echo "$out"; exit 1; }

# --- changelog / pyproject version drift is a hard error ---
mkdir -p "$work/repo"
for item in pyproject.toml debian runtime spec setup-brain-v2.sh; do
  cp -a "$PROJECT_ROOT/$item" "$work/repo/"
done
sed -i '1s/(0\.[0-9.]*)/(9.9.9)/' "$work/repo/debian/changelog"
if bash "$work/repo/runtime/packaging/build-deb.sh" --out-dir "$work/dist2" >/dev/null 2>&1; then
  echo "FAILED: build-deb.sh did not reject changelog/pyproject version drift"; exit 1
fi

echo "deb-build OK (brain-runtime ${version}, $(echo "$contents" | wc -l) entries)"
