# tests/lib/drop-git-env.sh — unset every GIT_* in the current shell.
# Source this file; do not execute it. Prefix walk, not a named denylist:
# GIT_OBJECT_DIRECTORY / GIT_COMMON_DIR / GIT_NAMESPACE and any future GIT_*
# would otherwise leak into nested git-using cases.
_git_keys=()
while IFS='=' read -r _k _; do
  case "$_k" in
    GIT_*) _git_keys+=("$_k") ;;
  esac
done < <(env)
if ((${#_git_keys[@]})); then
  unset -v "${_git_keys[@]}"
fi
unset _k _git_keys
