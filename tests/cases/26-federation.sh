#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying brain-federation read-only preflight"

brain-federation support --json >/tmp/brain_federation_support.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_support.json"))
assert data["ok"] is True, data
assert data["schema_version"] == 1, data
assert data["mode"] == "support", data
assert data["summary"]["block"] == 0, data
PYEOF

clean_active=$(mktemp)
cat >"$clean_active" <<'TASKS'
# Active Tasks

- [ ] [P1] t-clean — Clean task
      role: developer  mode: solo
      acceptance: ok
TASKS
brain-federation tasks-check --active "$clean_active" --json >/tmp/brain_federation_clean.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_clean.json"))
assert data["ok"] is True, data
assert data["summary"]["block"] == 0, data
assert data["findings"] == [], data
PYEOF

duplicate_active=$(mktemp)
cat >"$duplicate_active" <<'TASKS'
# Active Tasks

- [ ] [P1] t-dup — First title
      role: developer  mode: solo
      acceptance: one

- [ ] [P1] t-dup — Second title
      role: reviewer  mode: council
      acceptance: two
TASKS
set +e
brain-federation tasks-check --active "$duplicate_active" --json >/tmp/brain_federation_duplicate.json
dup_rc=$?
set -e
[ "$dup_rc" -eq 1 ] || fail_case "duplicate task id should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_duplicate.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "task-duplicate-id" in codes, data
assert "task-field-conflict" in codes, data
assert data["summary"]["block"] >= 2, data
PYEOF

in_progress_active=$(mktemp)
cat >"$in_progress_active" <<'TASKS'
# Active Tasks

- [~] [P1] t-imported — Imported in progress
      role: developer  mode: solo
      acceptance: should be open on import
      node: node-remote
TASKS
set +e
brain-federation tasks-check --active "$in_progress_active" --json >/tmp/brain_federation_in_progress.json
progress_rc=$?
set -e
[ "$progress_rc" -eq 1 ] || fail_case "imported in-progress task should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_in_progress.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "task-imported-in-progress" in codes, data
messages = " ".join(finding["message"] for finding in data["findings"])
assert "node-remote" in messages, data
PYEOF

active_open=$(mktemp)
done_done=$(mktemp)
cat >"$active_open" <<'TASKS'
- [ ] [P1] t-cross — Open copy
      role: developer  mode: solo
      acceptance: open
TASKS
cat >"$done_done" <<'TASKS'
- [x] [P1] t-cross — Done copy
      role: developer  mode: solo
      acceptance: done
TASKS
set +e
brain-federation tasks-check --active "$active_open" --done "$done_done" --json >/tmp/brain_federation_cross.json
cross_rc=$?
set -e
[ "$cross_rc" -eq 1 ] || fail_case "active/done conflict should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_cross.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "task-done-open-conflict" in codes, data
PYEOF

repo=$(mktemp -d)
git -C "$repo" init -q
git -C "$repo" config user.email smoke@example.local
git -C "$repo" config user.name "Brain Smoke"
mkdir -p "$repo/raw" "$repo/wiki" "$repo/handoff"
cat >"$repo/raw/source.md" <<'RAW'
initial source
RAW
cat >"$repo/wiki/protected.md" <<'WIKI'
---
protected: true
curation: human
---

# Protected
WIKI
cat >"$repo/wiki/provider-matrix.json" <<'JSON'
{
  "version": 1,
  "roles": {
    "developer": [
      {"rank": 1, "provider": "gemini", "model": "3-flash", "command": "gemini -m old"}
    ]
  }
}
JSON
cat >"$repo/.gitignore" <<'GITIGNORE'
.brain/
.locks/
.provider-health.json
handoff/ORCHESTRATOR_HANDOFF.md
wiki/_views/
GITIGNORE
git -C "$repo" add .
git -C "$repo" commit -q -m initial

cat >"$repo/.provider-health.json" <<'JSON'
{"version": 1}
JSON
cat >"$repo/raw/source.md" <<'RAW'
changed source
RAW
cat >"$repo/wiki/protected.md" <<'WIKI'
---
protected: true
curation: human
---

# Protected edit
WIKI
cat >"$repo/wiki/provider-matrix.json" <<'JSON'
{
  "version": 1,
  "roles": {
    "developer": [
      {"rank": 1, "provider": "gemini", "model": "3-flash", "command": "gemini -m new"}
    ]
  }
}
JSON

set +e
brain-federation preflight --repo "$repo" --brain "$BRAIN_PATH" --json >/tmp/brain_federation_preflight.json
preflight_rc=$?
set -e
[ "$preflight_rc" -eq 1 ] || fail_case "preflight with blocking findings should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_preflight.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "runtime-file-included" in codes, data
assert "raw-rewrite" in codes, data
assert "protected-wiki-edit" in codes, data
assert "human-curated-wiki-edit" in codes, data
assert "provider-matrix-change" in codes, data
assert "provider-command-change" in codes, data
assert data["summary"]["block"] >= 4, data
assert data["summary"]["review"] >= 2, data
PYEOF

model_repo=$(mktemp -d)
git -C "$model_repo" init -q
git -C "$model_repo" config user.email smoke@example.local
git -C "$model_repo" config user.name "Brain Smoke"
mkdir -p "$model_repo/wiki"
cat >"$model_repo/.gitignore" <<'GITIGNORE'
.brain/
.locks/
.provider-health.json
handoff/ORCHESTRATOR_HANDOFF.md
wiki/_views/
GITIGNORE
cat >"$model_repo/wiki/provider-matrix.json" <<'JSON'
{
  "version": 1,
  "roles": {
    "developer": [
      {"rank": 1, "provider": "gemini", "model": "old-model", "command": "gemini -m stable"}
    ]
  }
}
JSON
git -C "$model_repo" add .
git -C "$model_repo" commit -q -m initial
cat >"$model_repo/wiki/provider-matrix.json" <<'JSON'
{
  "version": 1,
  "roles": {
    "developer": [
      {"rank": 1, "provider": "gemini", "model": "new-model", "command": "gemini -m stable"}
    ]
  }
}
JSON
brain-federation preflight --repo "$model_repo" --brain "$BRAIN_PATH" --json >/tmp/brain_federation_provider_model.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_provider_model.json"))
codes = {finding["code"] for finding in data["findings"]}
assert data["ok"] is True, data
assert "provider-matrix-change" in codes, data
assert data["summary"]["review"] >= 1, data
assert data["summary"]["block"] == 0, data
PYEOF

BRAIN_SECRET_SCANNER_CMD="missing-brain-secret-scanner" brain-federation preflight --repo "$model_repo" --brain "$BRAIN_PATH" --json >/tmp/brain_federation_missing_scanner.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_missing_scanner.json"))
codes = {finding["code"] for finding in data["findings"]}
assert data["ok"] is True, data
assert "secret-scanner-unavailable" in codes, data
assert data["summary"]["warn"] >= 1, data
assert data["summary"]["block"] == 0, data
PYEOF

mock_scanner=$(mktemp)
cat >"$mock_scanner" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' '{"code":"mock-secret","severity":"block","path":"wiki/provider-matrix.json","message":"mock scanner found a secret","hint":"remove it"}'
MOCK
chmod +x "$mock_scanner"
set +e
BRAIN_SECRET_SCANNER_CMD="$mock_scanner" brain-federation preflight --repo "$model_repo" --brain "$BRAIN_PATH" --json >/tmp/brain_federation_mock_scanner.json
mock_scanner_rc=$?
set -e
[ "$mock_scanner_rc" -eq 1 ] || fail_case "mock scanner block finding should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_mock_scanner.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "mock-secret" in codes, data
assert data["summary"]["block"] >= 1, data
PYEOF

plan_brain=$(mktemp -d)
mkdir -p "$plan_brain/tasks" "$plan_brain/wiki"
cat >"$plan_brain/tasks/active.md" <<'TASKS'
# Active
TASKS
cat >"$plan_brain/tasks/done.md" <<'TASKS'
# Done
TASKS
plan_repo=$(mktemp -d)
git -C "$plan_repo" init -q
git -C "$plan_repo" config user.email smoke@example.local
git -C "$plan_repo" config user.name "Brain Smoke"
mkdir -p "$plan_repo/tasks"
cat >"$plan_repo/tasks/active.md" <<'TASKS'
# Active

- [ ] [P1] t-plan-clean — Plan clean task
      role: developer  mode: solo
      acceptance: importable
TASKS
cat >"$plan_repo/tasks/done.md" <<'TASKS'
# Done
TASKS
cat >"$plan_repo/.gitignore" <<'GITIGNORE'
.brain/
.locks/
.provider-health.json
handoff/ORCHESTRATOR_HANDOFF.md
wiki/_views/
GITIGNORE
git -C "$plan_repo" add .
git -C "$plan_repo" commit -q -m initial

before_plan_hash=$(find "$plan_brain" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
brain-federation plan --repo "$plan_repo" --brain "$plan_brain" --json >/tmp/brain_federation_plan_clean.json
after_plan_hash=$(find "$plan_brain" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
[ "$before_plan_hash" = "$after_plan_hash" ] || fail_case "plan --json should not write to brain"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_plan_clean.json"))
assert data["ok"] is True, data
assert data["mode"] == "plan", data
assert data["read_only"] is True, data
assert data["summary"]["block"] == 0, data
assert data["preflight"]["summary"]["block"] == 0, data
assert [item["id"] for item in data["task_imports"]] == ["t-plan-clean"], data
assert data["task_imports"][0]["state"] == "open", data
assert data["required_confirmations"] == [], data
PYEOF

plan_out=$(mktemp)
rm -f "$plan_out"
before_out_hash=$(find "$plan_brain" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
brain-federation plan --repo "$plan_repo" --brain "$plan_brain" --out "$plan_out" >/tmp/brain_federation_plan_out.txt
after_out_hash=$(find "$plan_brain" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
[ "$before_out_hash" = "$after_out_hash" ] || fail_case "plan --out should only write the requested plan file"
[ -f "$plan_out" ] || fail_case "plan --out did not write requested file"
python3 - "$plan_out" <<'PYEOF'
import json
import sys
data = json.load(open(sys.argv[1]))
assert data["mode"] == "plan", data
assert data["kind"] == "federation-plan", data
assert data["generated_at"], data
assert data["plan_id"].startswith("sha256:"), data
assert data["source_state"]["brain_active_sha256"].startswith("sha256:"), data
assert data["source_state"]["brain_done_sha256"].startswith("sha256:"), data
assert data["task_imports"][0]["id"] == "t-plan-clean", data
PYEOF

before_import_hash=$(sha256sum "$plan_brain/tasks/active.md" | awk '{print $1}')
brain-federation import-tasks --plan "$plan_out" --as smoke-importer --json >/tmp/brain_federation_import_dryrun.json
after_import_hash=$(sha256sum "$plan_brain/tasks/active.md" | awk '{print $1}')
[ "$before_import_hash" = "$after_import_hash" ] || fail_case "import-tasks dry-run should not write active.md"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_import_dryrun.json"))
assert data["ok"] is True, data
assert data["mode"] == "import-tasks", data
assert data["dry_run"] is True, data
assert data["would_import"] == 1, data
assert data["imported"] == [], data
PYEOF

brain-federation import-tasks --plan "$plan_out" --as smoke-importer --yes --json >/tmp/brain_federation_import_yes.json
grep -q "t-plan-clean" "$plan_brain/tasks/active.md" || fail_case "import-tasks --yes did not append task"
grep -q "federation-import-task | t-plan-clean | smoke-importer" "$plan_brain/wiki/log.md" || fail_case "import-tasks did not log imported task"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_import_yes.json"))
assert data["ok"] is True, data
assert data["dry_run"] is False, data
assert data["imported"] == ["t-plan-clean"], data
PYEOF

set +e
brain-federation import-tasks --plan "$plan_out" --as smoke-importer --yes --json >/tmp/brain_federation_import_stale.json
stale_rc=$?
set -e
[ "$stale_rc" -eq 1 ] || fail_case "reusing stale import plan should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_import_stale.json"))
codes = {finding["code"] for finding in data["findings"]}
assert data["ok"] is False, data
assert "plan-stale" in codes, data
PYEOF

conflict_brain=$(mktemp -d)
mkdir -p "$conflict_brain/tasks"
cat >"$conflict_brain/tasks/active.md" <<'TASKS'
# Active
TASKS
cat >"$conflict_brain/tasks/done.md" <<'TASKS'
- [x] [P1] t-plan-conflict — Local done
      role: developer  mode: solo
      acceptance: done
TASKS
conflict_repo=$(mktemp -d)
git -C "$conflict_repo" init -q
git -C "$conflict_repo" config user.email smoke@example.local
git -C "$conflict_repo" config user.name "Brain Smoke"
mkdir -p "$conflict_repo/tasks"
cat >"$conflict_repo/tasks/active.md" <<'TASKS'
- [ ] [P1] t-plan-conflict — Proposed open
      role: developer  mode: solo
      acceptance: open
TASKS
cat >"$conflict_repo/tasks/done.md" <<'TASKS'
# Done
TASKS
cat >"$conflict_repo/.gitignore" <<'GITIGNORE'
.brain/
.locks/
.provider-health.json
handoff/ORCHESTRATOR_HANDOFF.md
wiki/_views/
GITIGNORE
git -C "$conflict_repo" add .
git -C "$conflict_repo" commit -q -m initial
set +e
brain-federation plan --repo "$conflict_repo" --brain "$conflict_brain" --json >/tmp/brain_federation_plan_block.json
plan_block_rc=$?
set -e
[ "$plan_block_rc" -eq 1 ] || fail_case "plan with task conflict should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_plan_block.json"))
codes = {finding["code"] for finding in data["findings"]}
assert data["ok"] is False, data
assert "task-done-open-conflict" in codes, data
assert data["summary"]["block"] >= 1, data
PYEOF

plan_block_out=$(mktemp)
brain-federation plan --repo "$conflict_repo" --brain "$conflict_brain" --out "$plan_block_out" >/tmp/brain_federation_plan_block_out.txt || true
set +e
brain-federation import-tasks --plan "$plan_block_out" --as smoke-importer --yes --json >/tmp/brain_federation_import_blocked.json
blocked_import_rc=$?
set -e
[ "$blocked_import_rc" -eq 1 ] || fail_case "importing blocked plan should exit 1"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_import_blocked.json"))
codes = {finding["code"] for finding in data["findings"]}
assert "plan-block-findings" in codes, data
assert data["imported"] == [], data
PYEOF

review_brain=$(mktemp -d)
mkdir -p "$review_brain/tasks"
cat >"$review_brain/tasks/active.md" <<'TASKS'
- [~] [P1] t-local-progress — Local in progress is not imported
      role: developer  mode: solo
      acceptance: local state
TASKS
cat >"$review_brain/tasks/done.md" <<'TASKS'
# Done
TASKS
brain-federation plan --repo "$model_repo" --brain "$review_brain" --json >/tmp/brain_federation_plan_review.json
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_plan_review.json"))
codes = {finding["code"] for finding in data["findings"]}
assert data["ok"] is True, data
assert "provider-matrix-change" in codes, data
assert "task-imported-in-progress" not in codes, data
assert data["summary"]["review"] >= 1, data
assert data["summary"]["block"] == 0, data
assert "provider-matrix-change" in data["required_confirmations"], data
PYEOF

proposal_brain=$(mktemp -d)
mkdir -p "$proposal_brain/tasks" "$proposal_brain/wiki"
cat >"$proposal_brain/tasks/active.md" <<'TASKS'
# Active
TASKS
cat >"$proposal_brain/tasks/done.md" <<'TASKS'
# Done
TASKS
cat >"$proposal_brain/wiki/protected.md" <<'WIKI'
---
protected: true
curation: human
---

# Local Protected
WIKI
proposal_repo=$(mktemp -d)
git -C "$proposal_repo" init -q
git -C "$proposal_repo" config user.email smoke@example.local
git -C "$proposal_repo" config user.name "Brain Smoke"
mkdir -p "$proposal_repo/wiki"
cat >"$proposal_repo/wiki/protected.md" <<'WIKI'
---
protected: true
curation: human
---

# Local Protected
WIKI
cat >"$proposal_repo/.gitignore" <<'GITIGNORE'
.brain/
.locks/
.provider-health.json
handoff/ORCHESTRATOR_HANDOFF.md
wiki/_views/
GITIGNORE
git -C "$proposal_repo" add .
git -C "$proposal_repo" commit -q -m initial
cat >"$proposal_repo/wiki/protected.md" <<'WIKI'
---
protected: true
curation: human
---

# Proposed Protected
WIKI
proposal_plan=$(mktemp)
brain-federation plan --repo "$proposal_repo" --brain "$proposal_brain" --out "$proposal_plan" >/tmp/brain_federation_proposal_plan.txt || true
python3 - "$proposal_plan" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
paths = {item["path"] for item in data["wiki_proposals"]}
assert "wiki/protected.md" in paths, data
assert data["skipped_wiki"] == [], data
PYEOF
before_wiki_hash=$(sha256sum "$proposal_brain/wiki/protected.md" | awk '{print $1}')
brain-federation write-wiki-proposals --plan "$proposal_plan" --as smoke-proposer --json >/tmp/brain_federation_proposal_dryrun.json
after_wiki_hash=$(sha256sum "$proposal_brain/wiki/protected.md" | awk '{print $1}')
[ "$before_wiki_hash" = "$after_wiki_hash" ] || fail_case "write-wiki-proposals dry-run should not mutate wiki"
[ ! -d "$proposal_brain/proposals" ] || fail_case "write-wiki-proposals dry-run should not create proposal dir"
python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_proposal_dryrun.json"))
assert data["ok"] is True, data
assert data["dry_run"] is True, data
assert data["would_write"] == 1, data
PYEOF
brain-federation write-wiki-proposals --plan "$proposal_plan" --as smoke-proposer --yes --json >/tmp/brain_federation_proposal_yes.json
after_yes_hash=$(sha256sum "$proposal_brain/wiki/protected.md" | awk '{print $1}')
[ "$before_wiki_hash" = "$after_yes_hash" ] || fail_case "write-wiki-proposals --yes must not mutate wiki"
proposal_dir=$(python3 - <<'PYEOF'
import json
data = json.load(open("/tmp/brain_federation_proposal_yes.json"))
print(data["proposal_dir"])
PYEOF
)
[ -f "$proposal_dir/manifest.json" ] || fail_case "proposal manifest missing"
[ -f "$proposal_dir/wiki/protected.md" ] || fail_case "proposal markdown missing"
[ -f "$proposal_dir/wiki/protected.md.diff" ] || fail_case "proposal diff missing"
[ -f "$proposal_dir/wiki/protected.md.meta.json" ] || fail_case "proposal meta missing"
grep -q "Proposed Protected" "$proposal_dir/wiki/protected.md" || fail_case "proposal markdown missing source content"
grep -q "federation-proposal-batch | write-wiki-proposals | smoke-proposer" "$proposal_brain/wiki/log.md" || fail_case "proposal writer did not log batch"

echo "brain-federation preflight OK"
