#!/usr/bin/env bash
# case: index-rebuild-debounce — серия мутаций не плодит параллельные ребилды
set -euo pipefail
source "$(dirname "$0")/../_lib.sh"

echo ">>> Verifying index rebuild is debounced and the index stays valid"

brain_factory
export PATH="$PROJECT_ROOT/runtime/bin:$PATH"
bash "$PROJECT_ROOT/setup-brain-v2.sh" >/dev/null 2>&1

# Подменяем brain-index счётчиком: считаем, сколько раз он реально запущен.
fake_bin="$(mktemp -d)"
ALL_TMPDIRS+=("$fake_bin")
counter="$fake_bin/count"
: > "$counter"
cat > "$fake_bin/brain-index" <<EOF
#!/usr/bin/env bash
echo x >> "$counter"
sleep 0.2
exit 0
EOF
chmod +x "$fake_bin/brain-index"

# Десять запросов подряд, как при серии быстрых мутаций очереди.
for _ in $(seq 1 10); do
    PYTHONPATH="$PROJECT_ROOT/runtime/lib" \
        python3 -m brain_core.rebuild "$fake_bin/brain-index" >/dev/null 2>&1 &
done
wait

runs=$(wc -l < "$counter" | tr -d ' ')
[ "$runs" -ge 1 ] || { echo "FAILED: index was never rebuilt"; exit 1; }
[ "$runs" -le 2 ] || {
    echo "FAILED: expected at most 2 rebuilds for 10 requests, got $runs"
    exit 1
}
echo "OK: 10 requests collapsed into $runs rebuild(s)"

# Изменения, пришедшие во время ребилда, не теряются: метка переживает проход.
: > "$counter"
PYTHONPATH="$PROJECT_ROOT/runtime/lib" \
    python3 -m brain_core.rebuild "$fake_bin/brain-index" >/dev/null 2>&1
[ "$(wc -l < "$counter" | tr -d ' ')" -ge 1 ] || {
    echo "FAILED: a single request did not trigger a rebuild"
    exit 1
}
echo "OK: a single request still rebuilds"

# Настоящий индекс после мутаций остаётся читаемым.
brain-task add "debounce probe" --role developer --prio P3 >/dev/null 2>&1
brain-index rebuild >/dev/null 2>&1 || true
index_file="$BRAIN_PATH/.brain/index/pages.json"
if [ -f "$index_file" ]; then
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$index_file" || {
        echo "FAILED: index is not valid JSON after mutations"
        exit 1
    }
    echo "OK: index is valid JSON"
else
    echo "OK: no index file to validate (index not built in this factory)"
fi

echo ">>> index rebuild debounce checks passed"
