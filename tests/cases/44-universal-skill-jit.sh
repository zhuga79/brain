#!/usr/bin/env bash
# Auto-extracted case file — runs in environment set by run.sh
set -euo pipefail
if [ -z "${PROJECT_ROOT:-}" ]; then
  PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying Just-In-Time skill injection in brain-run"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
BRAIN_PATH="$BRAIN_PATH" bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null

mkdir -p "$HOME/.codex"
chmod 500 "$HOME/.codex"
set +e
no_skill_out=$(brain-run --role lawyer --client codex --task t-no-such 2>&1)
no_skill_rc=$?
set -e
chmod 700 "$HOME/.codex"
[ "$no_skill_rc" -eq 0 ] || {
  echo "FAILED: brain-run no-skill case exited $no_skill_rc"
  echo "$no_skill_out"
  exit 1
}
echo "$no_skill_out" | grep -q "JIT Injection Error" && {
  echo "FAILED: brain-run attempted JIT config write when no skills apply"
  echo "$no_skill_out"
  exit 1
}
echo "brain-run no-skill JIT no-op OK"

mkdir -p "$BRAIN_PATH/skills/test-mcp"
cat << 'YAMLEOF' > "$BRAIN_PATH/skills/test-mcp/SKILL.md"
---
name: playwright-test
type: mcp
applies_to: [developer]
supported_clients: [claude, gemini, codex, opencode, kilocode]
mcp_command: "npx @playwright/mcp"
---
This is a test MCP skill.
YAMLEOF

mkdir -p "$BRAIN_PATH/skills/test-knowledge"
cat << 'YAMLEOF' > "$BRAIN_PATH/skills/test-knowledge/SKILL.md"
---
name: clean-arch-mock
type: knowledge
applies_to: [architect, developer]
supported_clients: [all]
---
Knowledge skill content block.
YAMLEOF

export HOME="$BRAIN_FACTORY_TMP/fake-home"
mkdir -p "$HOME/.claude"
mkdir -p "$HOME/.gemini"
mkdir -p "$HOME/.codex"
mkdir -p "$HOME/.opencode"

# Create fake active.md and roles
mkdir -p "$BRAIN_PATH/tasks" "$BRAIN_PATH/roles" "$BRAIN_PATH/wiki"
cat << 'EOF' > "$BRAIN_PATH/tasks/active.md"
# Active tasks
- [ ] [P1] t-mock — Mock task
      role: developer
      mode: solo
EOF
touch "$BRAIN_PATH/roles/developer.md"
touch "$BRAIN_PATH/roles/architect.md"
touch "$BRAIN_PATH/MEMORY.md"
touch "$BRAIN_PATH/wiki/index.md"

cd "$BRAIN_PATH"

# Test claude client with developer role (expects both mcp and knowledge)
out_claude=$(brain-run --role developer --client claude --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_claude" || { echo "FAILED: Missing knowledge block in stdout"; exit 1; }
grep -q "playwright-test" "$HOME/.claude/settings.local.json" || { echo "FAILED: Missing MCP JIT in settings.local.json"; exit 1; }

# Test codex client with developer role (expects both mcp and knowledge)
out_codex=$(brain-run --role developer --client codex --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_codex" || { echo "FAILED: Missing knowledge block in stdout for codex"; exit 1; }
grep -q "playwright-test" "$HOME/.codex/settings.json" || { echo "FAILED: Missing MCP JIT in codex settings.json"; exit 1; }

# Test opencode client with developer role (expects both mcp and knowledge)
out_opencode=$(brain-run --role developer --client opencode --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_opencode" || { echo "FAILED: Missing knowledge block in stdout for opencode"; exit 1; }
grep -q "playwright-test" ".opencode.json" || { echo "FAILED: Missing MCP JIT in .opencode.json"; exit 1; }

# Test kilocode client with developer role (expects both mcp and knowledge)
out_kilocode=$(brain-run --role developer --client kilocode --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_kilocode" || { echo "FAILED: Missing knowledge block in stdout for kilocode"; exit 1; }
grep -q "playwright-test" ".kilocode/mcp.json" || { echo "FAILED: Missing MCP JIT in .kilocode/mcp.json"; exit 1; }

# Test ollama client with developer role (expects knowledge, no MCP modifications)
rm -f "$HOME/.claude/settings.local.json"
out_ollama=$(brain-run --role developer --client ollama --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_ollama" || { echo "FAILED: Missing knowledge block for ollama"; exit 1; }
if [ -f "$HOME/.claude/settings.local.json" ]; then
    grep -q "playwright-test" "$HOME/.claude/settings.local.json" && { echo "FAILED: ollama triggered claude MCP config injection"; exit 1; } || true
fi

# Test architect role with claude (expects knowledge, NO playwright MCP)
cat << 'JSONEOF' > "$HOME/.claude/settings.local.json"
{
  "mcpServers": {
    "playwright-test": {"command": "npx"},
    "brain": {"command": "brain-mcp"}
  }
}
JSONEOF

out_arch=$(brain-run --role architect --client claude --task t-mock)
grep -q "Knowledge skill content block" <<< "$out_arch" || { echo "FAILED: Architect missing knowledge block"; exit 1; }
grep -q "playwright-test" "$HOME/.claude/settings.local.json" && { echo "FAILED: Architect still has developer MCP tool in config"; exit 1; }
grep -q "brain" "$HOME/.claude/settings.local.json" || { echo "FAILED: Architect removed brain MCP tool from config"; exit 1; }

echo "JIT Skill Injection OK"
