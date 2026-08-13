#!/usr/bin/env bash
# install-obsidian-skills.sh -- optional Brain integration for kepano/obsidian-skills.
#
# Installs upstream Agent Skills into Codex' skills directory without vendoring
# the repository into Brain. Existing skill directories are skipped unless
# --force is passed.

set -euo pipefail

REPO_URL="${OBSIDIAN_SKILLS_REPO:-https://github.com/kepano/obsidian-skills.git}"
REF="${OBSIDIAN_SKILLS_REF:-main}"
DEST="${CODEX_HOME:-$HOME/.codex}/skills"
FORCE=0

usage() {
  cat <<'USAGE'
Usage: bash install-obsidian-skills.sh [--dest PATH] [--ref REF] [--force]

Installs these upstream skills:
  obsidian-markdown
  obsidian-bases
  json-canvas
  obsidian-cli
  defuddle

Options:
  --dest PATH   Destination skills directory (default: $CODEX_HOME/skills or ~/.codex/skills)
  --ref REF     Git ref to install (default: main)
  --force       Replace existing destination skill directories
  -h, --help    Show this help

Environment:
  OBSIDIAN_SKILLS_REPO   Override repository URL
  OBSIDIAN_SKILLS_REF    Override git ref
  CODEX_HOME             Base Codex directory
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dest)
      [ "$#" -ge 2 ] || { echo "ERROR: --dest requires a path" >&2; exit 2; }
      DEST="$2"
      shift 2
      ;;
    --ref)
      [ "$#" -ge 2 ] || { echo "ERROR: --ref requires a git ref" >&2; exit 2; }
      REF="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "ERROR: git is required" >&2; exit 1; }

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo ">>> Cloning $REPO_URL#$REF"
git clone --depth 1 --branch "$REF" "$REPO_URL" "$TMP_DIR/obsidian-skills" >/dev/null

mkdir -p "$DEST"

skills=(
  obsidian-markdown
  obsidian-bases
  json-canvas
  obsidian-cli
  defuddle
)

for skill in "${skills[@]}"; do
  src="$TMP_DIR/obsidian-skills/skills/$skill"
  dst="$DEST/$skill"
  [ -d "$src" ] || { echo "ERROR: missing upstream skill: $skill" >&2; exit 1; }

  if [ -e "$dst" ]; then
    if [ "$FORCE" -eq 1 ]; then
      rm -rf "$dst"
    else
      echo "  skip $skill (already exists)"
      continue
    fi
  fi

  cp -R "$src" "$dst"
  echo "  installed $skill -> $dst"
done

cat <<INFO

Done.
Restart Codex to pick up new skills.

Source: https://github.com/kepano/obsidian-skills
License: MIT
INFO
