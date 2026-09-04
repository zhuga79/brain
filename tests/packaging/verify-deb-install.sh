#!/usr/bin/env bash
# verify-deb-install.sh — build brain-runtime_<version>_all.deb and install it
# into clean debian:stable and ubuntu:latest containers, then check the CLI is
# on PATH, the reported Core version is not "unpackaged", a factory vault
# bootstraps and brain-validate passes.
#
# Docker is required. Without it (or with BRAIN_SKIP_DEB_CONTAINER_TEST set)
# the script SKIPs (exit 0) so the smoke runner can call it cheaply; the
# deb-install CI job runs it for real.
#
# Usage: bash tests/packaging/verify-deb-install.sh [image ...]
set -euo pipefail

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGES=("$@")
[ "${#IMAGES[@]}" -gt 0 ] || IMAGES=(debian:stable ubuntu:latest)

if [ -n "${BRAIN_SKIP_DEB_CONTAINER_TEST:-}" ]; then
  echo "SKIP: BRAIN_SKIP_DEB_CONTAINER_TEST set"
  exit 0
fi
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "SKIP: docker not available — CI runs this for real"
  exit 0
fi
for tool in dpkg-deb fakeroot; do
  command -v "$tool" >/dev/null 2>&1 || { echo "SKIP: missing $tool"; exit 0; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo ">>> building the package"
bash "$REPO_ROOT/runtime/packaging/build-deb.sh" --out-dir "$work/dist" >/dev/null
deb="$(ls "$work/dist"/brain-runtime_*_all.deb)"
deb_name="$(basename "$deb")"
version="$(dpkg-deb --field "$deb" Version)"
echo "    $deb_name (version $version)"

# The in-container check. $DEB_NAME / $VERSION are substituted by the caller.
container_script='
set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# apt resolves python3 (>= 3.10), git, jq from the package Depends
apt-get install -y -qq "/deb/__DEB_NAME__"

command -v brain-task     || { echo "FAIL: brain-task not on PATH"; exit 1; }
command -v brain-validate || { echo "FAIL: brain-validate not on PATH"; exit 1; }
command -v brain-federation || { echo "FAIL: brain-federation not on PATH"; exit 1; }

# the library must import off the default sys.path — no PYTHONPATH help
python3 -c "import brain_core.version, brain_task_parser, brain_federation.core"

git config --global user.email ci@brain.local
git config --global user.name  ci
export BRAIN_PATH=/tmp/vault
bash /usr/share/brain/setup-brain-v2.sh \
  --module pm-finance,design-negotiator,teams,power-features,tax-boundaries,doctrine >/dev/null

core_line="$(brain-status --brain /tmp/vault 2>/dev/null | sed -n "s/^Core: //p" || true)"
echo "Core line: ${core_line:-<none>}"
case "$core_line" in
  ""|unpackaged*) echo "FAIL: Core reported as \"${core_line:-empty}\""; exit 1 ;;
  __VERSION__*)   : ;;
  *)              echo "FAIL: Core version is not __VERSION__: $core_line"; exit 1 ;;
esac
case "$core_line" in
  *"dpkg:brain-runtime"*) : ;;
  *) echo "FAIL: Core location is not dpkg:brain-runtime: $core_line"; exit 1 ;;
esac

brain-validate --brain /tmp/vault
echo "OK: __IMAGE__"
'

rc=0
for image in "${IMAGES[@]}"; do
  echo ">>> $image"
  script="${container_script//__DEB_NAME__/$deb_name}"
  script="${script//__VERSION__/$version}"
  script="${script//__IMAGE__/$image}"
  if docker run --rm -v "$work/dist:/deb:ro" "$image" bash -c "$script"; then
    echo "    $image OK"
  else
    echo "    $image FAILED"
    rc=1
  fi
done

[ "$rc" -eq 0 ] && echo ">>> deb install verified on: ${IMAGES[*]}"
exit "$rc"
