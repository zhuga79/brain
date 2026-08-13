#!/bin/bash
# Brain Dashboard launcher: focus existing window if present, otherwise start server and open.

export PATH="$HOME/.local/bin:$PATH"
export BRAIN_PATH="${BRAIN_PATH:-$HOME/brain}"

# Local, machine-specific overrides (paths to private project folders, etc.).
# This file is gitignored — keep real workspace roots there, not in this script.
if [ -f "$HOME/.config/brain/dashboard-env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.config/brain/dashboard-env"
fi

# Colon-separated roots scanned for folder-native project workspaces (BRAIN.md).
# Override via the local env file above or your shell; defaults to Documents.
export BRAIN_DASHBOARD_WORKSPACE_ROOTS="${BRAIN_DASHBOARD_WORKSPACE_ROOTS:-$HOME/Documents}"

PORT=8765
URL="http://127.0.0.1:${PORT}/"

for flag in CODEX_SANDBOX_NETWORK_DISABLED CODEX_SANDBOX SANDBOX_MODE BRAIN_SANDBOX_AGENT_LAUNCH_GUARD; do
    value="${!flag:-}"
    case "$value" in
        ""|0|false|False|no|NO) ;;
        *)
            echo "Refusing to start Brain Dashboard server from Codex sandbox (${flag}=${value})." >&2
            echo "Start it from a normal desktop terminal/session so live agent launches are outside sandbox." >&2
            exit 2
            ;;
    esac
done

# 1) Focus existing window if any (X11 only).
if command -v wmctrl >/dev/null 2>&1 && wmctrl -a "Brain Dashboard" 2>/dev/null; then
    exit 0
fi

# 2) Ensure server is up — port-based check (avoids pgrep self-match bug).
if ! curl -sS --noproxy 127.0.0.1 --connect-timeout 1 -o /dev/null "$URL" 2>/dev/null; then
    nohup brain-dashboard serve --port "$PORT" >/tmp/brain-dashboard.log 2>&1 < /dev/null &
    disown
fi

# 3) Wait up to ~9s for server readiness.
for _ in $(seq 1 30); do
    curl -sS --noproxy 127.0.0.1 -o /dev/null "$URL" 2>/dev/null && break
    sleep 0.3
done

# 4) Open in default browser.
xdg-open "$URL" >/dev/null 2>&1
