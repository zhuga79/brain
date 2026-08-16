#!/usr/bin/env bash
# tests/lib/provider-stubs.sh — заглушки провайдерских CLI для песочницы.
#
# Зачем. Смоук проверяет маршрутизацию: какой провайдер выбран для роли, что
# показывает `brain-provider status`, что печатает `brain-launch --dry-run`.
# Решение зависит от того, лежит ли исполняемый файл провайдера на PATH
# (`brain_provider._command_probe` → `shutil.which`). На машине оператора
# codex/gemini/claude/opencode установлены, на чистом раннере GitHub — нет,
# и один и тот же коммит давал 100/100 локально и 92/100 в CI: пять кейсов
# (07, 09, 33, 81, 89) читали не свою конфигурацию, а состав софта на хосте.
#
# Поэтому состав провайдеров задаёт сама песочница, а не хост. Каталог
# заглушек встаёт в начало PATH: он перекрывает и настоящие CLI оператора —
# гейт обязан отвечать одинаково везде, иначе «зелено» ничего не значит.
#
# Заглушка отвечает только на `--version` (этим пользуется `brain-provider
# probe`) и на любой другой вызов выходит нулём, ничего не делая. Stdin она
# не читает намеренно: `opencode models` и подобные вызовы идут с
# унаследованным stdin, и `cat` в заглушке завис бы до таймаута.

# Список общий с фикстурой pytest — см. tests/lib/provider-clis.txt.
BRAIN_TEST_PROVIDER_STUBS=()
while IFS= read -r _line; do
    case "$_line" in ''|'#'*) continue;; esac
    BRAIN_TEST_PROVIDER_STUBS+=("$_line")
done < "$(dirname "${BASH_SOURCE[0]}")/provider-clis.txt"
unset _line

# make_provider_stubs <dir> — создать заглушки в каталоге и напечатать его путь.
make_provider_stubs() {
    local dir="$1"
    mkdir -p "$dir"
    local name
    for name in "${BRAIN_TEST_PROVIDER_STUBS[@]}"; do
        cat > "$dir/$name" <<EOF
#!/usr/bin/env bash
# Заглушка провайдерского CLI (tests/lib/provider-stubs.sh).
case "\${1:-}" in
    --version|-v|version) echo "$name 0.0.0-test-stub"; exit 0 ;;
esac
exit 0
EOF
        chmod 755 "$dir/$name"
    done
    printf '%s\n' "$dir"
}
