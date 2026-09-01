#!/usr/bin/env bash
# case: council-team-listing — merge data and system team catalogs
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

COUNCIL_BIN="$PROJECT_ROOT/runtime/bin/brain-council"

write_role() {
  local root="$1" name="$2"
  mkdir -p "$root/roles"
  cat > "$root/roles/${name}.md" <<EOF
---
type: role
doctrine: []
model_tier: fast
writes: [code]
---
# Role: ${name}
EOF
}

write_team() {
  local dir="$1" name="$2" roles="$3"
  mkdir -p "$dir"
  cat > "$dir/${name}.md" <<EOF
---
title: Team ${name}
type: team
roles: ${roles}
---
EOF
}

init_data_root() {
  mkdir -p "$BRAIN_PATH"/{tasks,wiki,council,raw,prd,.locks}
  printf '# Active\n' > "$BRAIN_PATH/tasks/active.md"
  printf '# Done\n' > "$BRAIN_PATH/tasks/done.md"
  printf '# Log\n' > "$BRAIN_PATH/wiki/log.md"
}

append_task() {
  local id="$1" team="$2"
  cat >> "$BRAIN_PATH/tasks/active.md" <<EOF

- [ ] [P1] ${id} — listing match
      role: developer
      mode: council
      council: [team:${team}]
EOF
}

count_named() {
  local out="$1" name="$2"
  printf '%s\n' "$out" | grep -cE "^${name}[[:space:]]" || true
}

expect_one_named() {
  local out="$1" name="$2"
  local n
  n=$(count_named "$out" "$name")
  [ "$n" = "1" ] || {
    echo "FAILED: expected exactly one '$name' line, got $n"
    echo "$out"
    exit 1
  }
}

expect_absent() {
  local out="$1" name="$2"
  local n
  n=$(count_named "$out" "$name")
  [ "$n" = "0" ] || {
    echo "FAILED: did not expect '$name' in listing"
    echo "$out"
    exit 1
  }
}

line_for() {
  local out="$1" name="$2"
  printf '%s\n' "$out" | grep -E "^${name}[[:space:]]" | head -1
}

expect_line_has() {
  local line="$1"
  shift
  local needle
  for needle in "$@"; do
    printf '%s\n' "$line" | grep -Fq "$needle" || {
      echo "FAILED: line missing '$needle'"
      echo "  line: $line"
      exit 1
    }
  done
}

expect_line_lacks() {
  local line="$1" needle="$2"
  printf '%s\n' "$line" | grep -Fq "$needle" && {
    echo "FAILED: line unexpectedly contains '$needle'"
    echo "  line: $line"
    exit 1
  } || true
}

roles_from_line() {
  local line="$1"
  printf '%s\n' "$line" | sed -E 's/^[^ ]+[[:space:]]+//; s/[[:space:]]+origin:.*$//' \
    | tr -d '[]' | tr ',' ' ' | xargs
}

assert_start_matches_listing() {
  local team="$1" listed_roles="$2"
  local tid="t-list-match-${team}"
  append_task "$tid" "$team"
  local start_out
  start_out=$("$COUNCIL_BIN" start "$tid" 2>&1) || {
    echo "FAILED: start did not resolve team:$team"
    echo "$start_out"
    exit 1
  }
  local start_roles
  start_roles=$(printf '%s\n' "$start_out" | grep -E '^roles:' | head -1 | sed 's/^roles: *//' | xargs)
  local listed_norm start_norm
  listed_norm=$(printf '%s\n' $listed_roles | LC_ALL=C sort | xargs)
  start_norm=$(printf '%s\n' $start_roles | LC_ALL=C sort | xargs)
  [ "$listed_norm" = "$start_norm" ] || {
    echo "FAILED: listing roles for $team do not match start resolution"
    echo "  listed: $listed_norm"
    echo "  start:  $start_norm"
    echo "$start_out"
    exit 1
  }
}

# ── split-root: merge, data-local precedence, origin/override labels ──
echo ">>> split-root listing merges catalogs and labels override"

brain_factory
data="$BRAIN_PATH"
system="$BRAIN_FACTORY_TMP/system"
export BRAIN_SYSTEM_PATH="$system"
init_data_root
write_role "$system" architect
write_role "$system" developer
write_role "$system" reviewer
write_role "$system" researcher
write_team "$system/teams" engineering "[architect, developer, reviewer]"
write_team "$system/teams" research "[researcher, reviewer]"
write_team "$data/teams" insurance-fraud "[reviewer]"
write_team "$data/teams" engineering "[developer]"

split_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero on split-root"
  echo "$split_out"
  exit 1
}

expect_one_named "$split_out" engineering
expect_one_named "$split_out" research
expect_one_named "$split_out" insurance-fraud

eng_line=$(line_for "$split_out" engineering)
research_line=$(line_for "$split_out" research)
fraud_line=$(line_for "$split_out" insurance-fraud)

expect_line_has "$eng_line" "[developer]" "origin:data" "override:system"
expect_line_lacks "$eng_line" "architect"
expect_line_lacks "$eng_line" "reviewer"

expect_line_has "$research_line" "[researcher, reviewer]" "origin:system"
expect_line_lacks "$research_line" "origin:data"
expect_line_lacks "$research_line" "override"

expect_line_has "$fraud_line" "[reviewer]" "origin:data"
expect_line_lacks "$fraud_line" "override"

printf '%s\n' "$split_out" | grep -Fq "(no teams)" && {
  echo "FAILED: split-root listing reported no teams"
  echo "$split_out"
  exit 1
}

# shellcheck source=/dev/null
source "$PROJECT_ROOT/runtime/bin/brain-common"
while IFS=$'\t' read -r name path origin; do
  resolved="$(brain_resolve_system "teams/${name}.md")"
  [ "$path" -ef "$resolved" ] || {
    echo "FAILED: listed path for $name does not match start resolve"
    echo "  listed: $path ($origin)"
    echo "  resolve: $resolved"
    exit 1
  }
done < <(brain_iter_team_files)

assert_start_matches_listing engineering "$(roles_from_line "$eng_line")"
assert_start_matches_listing research "$(roles_from_line "$research_line")"
assert_start_matches_listing insurance-fraud "$(roles_from_line "$fraud_line")"

[ -f "$data/council/t-list-match-engineering/developer.md" ] || {
  echo "FAILED: override team start did not use data-local developer"
  exit 1
}
[ ! -f "$data/council/t-list-match-engineering/architect.md" ] || {
  echo "FAILED: override team start fell through to system engineering roles"
  exit 1
}

echo "OK: split-root merge, override labels, start resolution"

# ── empty data/teams must not hide the system catalog ──
echo ">>> empty data/teams still lists system teams"

brain_factory
data="$BRAIN_PATH"
system="$BRAIN_FACTORY_TMP/system"
export BRAIN_SYSTEM_PATH="$system"
init_data_root
mkdir -p "$data/teams"
write_role "$system" architect
write_role "$system" developer
write_role "$system" reviewer
write_team "$system/teams" engineering "[architect, developer, reviewer]"

empty_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero on empty data/teams"
  echo "$empty_out"
  exit 1
}

expect_one_named "$empty_out" engineering
empty_eng=$(line_for "$empty_out" engineering)
expect_line_has "$empty_eng" "[architect, developer, reviewer]" "origin:system"
expect_line_lacks "$empty_eng" "origin:data"
printf '%s\n' "$empty_out" | grep -Fq "(no teams)" && {
  echo "FAILED: empty data/teams hid the system catalog"
  echo "$empty_out"
  exit 1
}

echo "OK: empty data/teams falls through to system"

# ── symlink: BRAIN_SYSTEM_PATH link, and data/teams link without duplication ──
echo ">>> symlink system root and data/teams link do not duplicate"

brain_factory
data="$BRAIN_PATH"
system_real="$BRAIN_FACTORY_TMP/system-real"
system_link="$BRAIN_FACTORY_TMP/system-link"
mkdir -p "$system_real"
ln -s "$system_real" "$system_link"
export BRAIN_SYSTEM_PATH="$system_link"
init_data_root
write_role "$system_real" architect
write_role "$system_real" developer
write_role "$system_real" reviewer
write_role "$system_real" researcher
write_team "$system_real/teams" engineering "[architect, developer, reviewer]"
write_team "$system_real/teams" research "[researcher, reviewer]"
write_team "$data/teams" insurance-fraud "[reviewer]"

symlink_root_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero with symlink system root"
  echo "$symlink_root_out"
  exit 1
}
expect_one_named "$symlink_root_out" engineering
expect_one_named "$symlink_root_out" research
expect_one_named "$symlink_root_out" insurance-fraud
expect_line_has "$(line_for "$symlink_root_out" engineering)" "origin:system"
expect_line_has "$(line_for "$symlink_root_out" insurance-fraud)" "origin:data"

rm -rf "$data/teams"
ln -s "$system_real/teams" "$data/teams"

symlink_dir_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero with data/teams symlink"
  echo "$symlink_dir_out"
  exit 1
}
expect_one_named "$symlink_dir_out" engineering
expect_one_named "$symlink_dir_out" research
expect_absent "$symlink_dir_out" insurance-fraud
expect_line_has "$(line_for "$symlink_dir_out" engineering)" "origin:system"
expect_line_lacks "$(line_for "$symlink_dir_out" engineering)" "override"
expect_line_lacks "$(line_for "$symlink_dir_out" research)" "origin:data"

# same-named data file that is a symlink to the system file is not an override
rm -rf "$data/teams"
mkdir -p "$data/teams"
ln -s "$system_real/teams/engineering.md" "$data/teams/engineering.md"
write_team "$data/teams" insurance-fraud "[reviewer]"

symlink_file_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero with team-file symlink"
  echo "$symlink_file_out"
  exit 1
}
expect_one_named "$symlink_file_out" engineering
expect_one_named "$symlink_file_out" research
expect_one_named "$symlink_file_out" insurance-fraud
expect_line_has "$(line_for "$symlink_file_out" engineering)" "origin:system"
expect_line_lacks "$(line_for "$symlink_file_out" engineering)" "override"
expect_line_has "$(line_for "$symlink_file_out" insurance-fraud)" "origin:data"

echo "OK: symlink catalog listing"

# ── legacy single-root: BRAIN_SYSTEM_PATH unset, no duplication ──
echo ">>> legacy single-root lists the one catalog once"

brain_factory
unset BRAIN_SYSTEM_PATH
init_data_root
write_role "$BRAIN_PATH" architect
write_role "$BRAIN_PATH" developer
write_role "$BRAIN_PATH" reviewer
write_team "$BRAIN_PATH/teams" engineering "[architect, developer, reviewer]"

legacy_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero on legacy single-root"
  echo "$legacy_out"
  exit 1
}
expect_one_named "$legacy_out" engineering
legacy_eng=$(line_for "$legacy_out" engineering)
expect_line_has "$legacy_eng" "[architect, developer, reviewer]" "origin:system"
expect_line_lacks "$legacy_eng" "override"
expect_line_lacks "$legacy_eng" "origin:data"

assert_start_matches_listing engineering "$(roles_from_line "$legacy_eng")"

echo "OK: legacy single-root listing"

# ── both catalogs empty ──
echo ">>> no teams when both catalogs are empty"

brain_factory
data="$BRAIN_PATH"
system="$BRAIN_FACTORY_TMP/system"
export BRAIN_SYSTEM_PATH="$system"
init_data_root
mkdir -p "$data/teams" "$system/teams"
none_out=$("$COUNCIL_BIN" teams 2>&1) || {
  echo "FAILED: brain-council teams exited non-zero on empty catalogs"
  echo "$none_out"
  exit 1
}
printf '%s\n' "$none_out" | grep -Fq "(no teams)" || {
  echo "FAILED: expected '(no teams)' for empty catalogs"
  echo "$none_out"
  exit 1
}

echo "OK: empty catalogs"
echo "brain-council team listing cross-root OK"
