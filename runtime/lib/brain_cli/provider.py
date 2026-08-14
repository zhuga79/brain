"""Inspect and explicitly refresh cached Brain provider health."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


import brain_provider  # noqa: E402


ALLOWED_STATUSES = {
    "configured",
    "available",
    "unavailable",
    "rate-limited",
    "quota-exhausted",
    "model-not-found",
    "auth-required",
    "error",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


from brain_core.paths import brain_path  # одна реализация на всю систему


def provider_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def sanitize_reason(value: str, limit: int = 240) -> str:
    clean = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean[:limit]


def strict_load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated": "", "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid provider health cache: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read provider health cache: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid provider health cache: root must be an object")
    items = data.get("items", {})
    if not isinstance(items, dict):
        raise ValueError("invalid provider health cache: items must be an object")
    data.setdefault("version", 1)
    data.setdefault("updated", "")
    data["items"] = items
    return data


def write_cache(path: Path, data: dict[str, Any]) -> None:
    data["version"] = int(data.get("version") or 1)
    data["updated"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def find_candidate(matrix: dict[str, Any], provider: str, model: str) -> dict[str, Any] | None:
    for candidate in brain_provider.iter_matrix_candidates(matrix):
        if candidate.get("provider") == provider and candidate.get("model") == model:
            return candidate
    return None


def filter_status(status: dict[str, Any], role: str = "", provider: str = "", model: str = "") -> dict[str, Any]:
    if not any((role, provider, model)):
        return status
    filtered = json.loads(json.dumps(status))
    roles = filtered.get("roles", {})
    for role_name in list(roles.keys()):
        if role and role_name != role:
            del roles[role_name]
            continue
        info = roles[role_name]
        for field in ("fallback", "unavailable", "candidates"):
            info[field] = [
                item
                for item in info.get(field, [])
                if (not provider or item.get("provider") == provider)
                and (not model or item.get("model") == model)
            ]
        preferred = info.get("preferred")
        if preferred and (
            (provider and preferred.get("provider") != provider)
            or (model and preferred.get("model") != model)
        ):
            info["preferred"] = info["fallback"][0] if info.get("fallback") else None
    return filtered


def print_status_text(status: dict[str, Any]) -> None:
    print("brain-provider status")
    print(f"  matrix: {status.get('source', '-')}")
    print(f"  health: {status.get('health_source') or '(none)'}")
    warning = status.get("health_warning") or status.get("warning")
    if warning:
        print(f"  warning: {warning}")
    for role, info in sorted((status.get("roles") or {}).items()):
        preferred = info.get("preferred") or {}
        if preferred:
            pref = f"{preferred.get('key')} [{preferred.get('status')}]"
        else:
            pref = "none"
        unavailable = len(info.get("unavailable") or [])
        # Профиль — то, что архитектор действительно решает про роль; без него
        # в выводе видно «какая модель», но не видно «почему такая».
        profile = f" profile={info['profile']}" if info.get("profile") else ""
        print(f"  {role}:{profile} preferred={pref} unavailable={unavailable}")


def cmd_status(args: argparse.Namespace) -> int:
    brain = brain_path(args.brain)
    status = filter_status(
        brain_provider.collect_provider_status(brain),
        role=args.role or "",
        provider=args.provider or "",
        model=args.model or "",
    )
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_status_text(status)
    return 0


def cmd_cli(args: argparse.Namespace) -> int:
    """Печатает команду запуска для роли — точка входа для bash-слоя.

    Всегда завершается нулём и всегда печатает команду: запускающий скрипт
    подставляет вывод в конвейер, и пустая строка там означала бы молчаливый
    отказ запустить роль. Причины и пропущенные кандидаты идут в stderr.
    """
    brain = brain_path(args.brain)
    result = brain_provider.resolve_for_role(
        brain,
        role=args.role,
        task=args.task or "",
        not_provider=args.not_provider or "",
        override=args.cli or os.environ.get("BRAIN_CLI_OVERRIDE", ""),
        author_provider=args.author_provider or "",
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for warning in result.get("warnings") or []:
        print(f"brain-provider cli: WARN {warning}", file=sys.stderr)
    if args.explain:
        for skipped in result.get("skipped") or []:
            print(f"brain-provider cli: пропущен {skipped}", file=sys.stderr)
        print(f"brain-provider cli: источник {result['source']} — {result['reason']}", file=sys.stderr)
    print(result["command"])
    return 0



def cmd_render_doc(args: argparse.Namespace) -> int:
    """Обновляет сгенерированный блок маршрутизации на странице решения."""
    brain = brain_path(args.brain)
    page = Path(args.page) if args.page else brain / "wiki" / "decision-llm-stack.md"
    new_text, changed = brain_provider.project_routing_doc(brain, page)
    if args.check:
        if changed:
            print(f"brain-provider render-doc: блок в {page} разошёлся с конфигурацией", file=sys.stderr)
            return 1
        print(f"brain-provider render-doc: {page} совпадает с конфигурацией")
        return 0
    page.write_text(new_text, encoding="utf-8")
    print(f"brain-provider render-doc: {'обновлено' if changed else 'без изменений'} — {page}")
    return 0


def probe_candidate(candidate: dict[str, Any], timeout: int) -> tuple[str, str]:
    execution = brain_provider.candidate_declares_nonlocal(candidate)
    if execution:
        return "configured", f"{execution} command declared"
    command = str(candidate.get("command", "")).strip()
    command_present, reason, _executable, resolved = brain_provider._command_probe(command)
    if not command_present:
        return "unavailable", reason
    try:
        res = subprocess.run(
            [resolved, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
        )
    except subprocess.TimeoutExpired:
        return "rate-limited", f"probe timed out after {timeout}s"
    except OSError as exc:
        return "error", f"probe failed: {exc}"
    if res.returncode == 0:
        return "available", "probe command succeeded"
    detail = sanitize_reason((res.stderr or res.stdout or f"exit={res.returncode}").strip())
    return "error", detail or f"probe failed with exit={res.returncode}"


def cache_item(provider: str, model: str, status: str, source: str, reason: str, ttl_seconds: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "status": status,
        "source": source,
        "reason": sanitize_reason(reason),
        "checked_at": utc_now(),
    }
    if ttl_seconds is not None:
        item["ttl_seconds"] = ttl_seconds
    return item


def cmd_refresh(args: argparse.Namespace) -> int:
    brain = brain_path(args.brain)
    matrix = brain_provider.load_provider_matrix(brain)
    candidate = find_candidate(matrix, args.provider, args.model)
    if candidate is None:
        print(f"brain-provider refresh: target not found in provider matrix: {provider_key(args.provider, args.model)}", file=sys.stderr)
        return 1

    if not args.yes:
        candidate = {**candidate, "command": brain_provider.candidate_command(matrix, candidate)}
        execution = brain_provider.candidate_declares_nonlocal(candidate)
        command_present, reason, executable, _resolved = brain_provider._command_probe(candidate["command"])
        msg = {
            "action": "refresh",
            "dry_run": True,
            "target": provider_key(args.provider, args.model),
            "planned_probe": (
                f"{execution} declaration"
                if execution else
                (f"{executable or '<empty>'} --version" if command_present else reason)
            ),
            "cache": str(brain_provider.health_path(brain)),
        }
        if args.json:
            print(json.dumps(msg, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"dry-run: would refresh {msg['target']}")
            print(f"  planned probe: {msg['planned_probe']}")
            print("  add --yes to run one bounded probe and update cache")
        return 0

    path = brain_provider.health_path(brain)
    try:
        data = strict_load_cache(path)
    except ValueError as exc:
        print(f"brain-provider refresh: {exc}", file=sys.stderr)
        return 1
    candidate = {**candidate, "command": brain_provider.candidate_command(matrix, candidate)}
    status, reason = probe_candidate(candidate, args.timeout)
    key = provider_key(args.provider, args.model)
    data.setdefault("items", {})[key] = cache_item(args.provider, args.model, status, "probe", reason, ttl_seconds=args.ttl_seconds)
    write_cache(path, data)
    if args.json:
        print(json.dumps({"ok": True, "key": key, "item": data["items"][key]}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"refreshed: {key} status={status}")
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    if args.status not in ALLOWED_STATUSES:
        print(f"brain-provider mark: invalid status: {args.status}", file=sys.stderr)
        return 2
    if not args.yes:
        print("brain-provider mark: --yes is required to mutate provider health cache", file=sys.stderr)
        return 2
    brain = brain_path(args.brain)
    path = brain_provider.health_path(brain)
    try:
        data = strict_load_cache(path)
    except ValueError as exc:
        print(f"brain-provider mark: {exc}", file=sys.stderr)
        return 1
    key = provider_key(args.provider, args.model)
    data.setdefault("items", {})[key] = cache_item(args.provider, args.model, args.status, "manual", args.reason, ttl_seconds=args.ttl_seconds)
    write_cache(path, data)
    if args.json:
        print(json.dumps({"ok": True, "key": key, "item": data["items"][key]}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"marked: {key} status={args.status}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    if not args.yes:
        print("brain-provider clear: --yes is required to mutate provider health cache", file=sys.stderr)
        return 2
    brain = brain_path(args.brain)
    path = brain_provider.health_path(brain)
    try:
        data = strict_load_cache(path)
    except ValueError as exc:
        print(f"brain-provider clear: {exc}", file=sys.stderr)
        return 1
    key = provider_key(args.provider, args.model)
    removed = data.setdefault("items", {}).pop(key, None) is not None
    write_cache(path, data)
    if args.json:
        print(json.dumps({"ok": True, "key": key, "removed": removed}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"cleared: {key}" if removed else f"not present: {key}")
    return 0


def is_within_ttl(item: dict[str, Any], ttl_seconds: int) -> bool:
    checked_at_str = item.get("checked_at")
    if not checked_at_str:
        return False
    try:
        checked_at = dt.datetime.strptime(checked_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - checked_at).total_seconds()
        # allow overriding ttl_seconds per item
        item_ttl = item.get("ttl_seconds")
        effective_ttl = item_ttl if item_ttl is not None else ttl_seconds
        return age <= effective_ttl
    except ValueError:
        return False

def cmd_probe(args: argparse.Namespace) -> int:
    brain = brain_path(args.brain)
    matrix = brain_provider.load_provider_matrix(brain)
    path = brain_provider.health_path(brain)
    try:
        data = strict_load_cache(path)
    except ValueError as exc:
        print(f"brain-provider probe: {exc}", file=sys.stderr)
        return 1

    candidates_to_probe = [
        {**candidate, "command": brain_provider.candidate_command(matrix, candidate)}
        for candidate in brain_provider.iter_matrix_candidates(matrix, args.role or "")
    ]

    # Deduplicate candidates by provider/model
    unique_candidates = {}
    for c in candidates_to_probe:
        k = provider_key(c.get("provider", ""), c.get("model", ""))
        if k not in unique_candidates:
            unique_candidates[k] = c

    items = data.setdefault("items", {})
    results = []
    
    for key, candidate in unique_candidates.items():
        existing = items.get(key)
        if existing and is_within_ttl(existing, args.ttl_sec):
            if not args.json:
                print(f"probe skipped (within TTL): {key} status={existing.get('status')}")
            continue

        status, reason = probe_candidate(candidate, args.timeout)
        prov = candidate.get("provider", "")
        mod = candidate.get("model", "")
        items[key] = cache_item(prov, mod, status, "probe", reason, ttl_seconds=args.ttl_sec)
        
        if not args.json:
            print(f"probed: {key} status={status}")
        results.append(items[key])

    write_cache(path, data)
    
    if args.json:
        print(json.dumps({"ok": True, "probed_count": len(results)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and explicitly refresh Brain provider health cache.")
    parser.add_argument("--brain", default=None, help="Brain path. Defaults to BRAIN_PATH or ~/brain.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status", help="Read provider matrix and cached health.")
    status.add_argument("--json", action="store_true", help="Emit JSON.")
    status.add_argument("--role", default="", help="Filter by role.")
    status.add_argument("--provider", default="", help="Filter by provider.")
    status.add_argument("--model", default="", help="Filter by model.")
    status.set_defaults(func=cmd_status)

    cli = sub.add_parser("cli", help="Print the launch command for a role.")
    cli.add_argument("--role", required=True)
    cli.add_argument("--task", default="", help="Task id — нужен для закрепления клиента скиллом.")
    cli.add_argument("--not-provider", default="", help="Исключить провайдера (правило диверсификации).")
    cli.add_argument("--author-provider", default="",
                     help="Провайдер автора работы: роли с diversify_from_author пойдут к другому.")
    cli.add_argument("--cli", default="", help="Явное указание команды: перекрывает конфигурацию.")
    cli.add_argument("--explain", action="store_true", help="Показать причину выбора в stderr.")
    cli.add_argument("--json", action="store_true", help="Emit JSON.")
    cli.set_defaults(func=cmd_cli)

    render_doc = sub.add_parser("render-doc", help="Спроецировать конфигурацию маршрутизации в страницу решения.")
    render_doc.add_argument("--page", default="", help="Страница. По умолчанию wiki/decision-llm-stack.md.")
    render_doc.add_argument("--check", action="store_true", help="Только проверить совпадение, ничего не писать.")
    render_doc.set_defaults(func=cmd_render_doc)

    refresh = sub.add_parser("refresh", help="Dry-run or run one bounded provider/model probe.")
    refresh.add_argument("--provider", required=True)
    refresh.add_argument("--model", required=True)
    refresh.add_argument("--timeout", type=int, default=30)
    refresh.add_argument("--ttl-seconds", type=int, default=3600)
    refresh.add_argument("--yes", action="store_true", help="Run the probe and update cache.")
    refresh.add_argument("--json", action="store_true", help="Emit JSON.")
    refresh.set_defaults(func=cmd_refresh)

    mark = sub.add_parser("mark", help="Manually mark cached provider/model health.")
    mark.add_argument("--provider", required=True)
    mark.add_argument("--model", required=True)
    mark.add_argument("--status", required=True, choices=sorted(ALLOWED_STATUSES))
    mark.add_argument("--reason", required=True)
    mark.add_argument("--ttl-seconds", type=int, default=None)
    mark.add_argument("--yes", action="store_true", help="Update cache.")
    mark.add_argument("--json", action="store_true", help="Emit JSON.")
    mark.set_defaults(func=cmd_mark)

    clear = sub.add_parser("clear", help="Remove one cached provider/model health item.")
    clear.add_argument("--provider", required=True)
    clear.add_argument("--model", required=True)
    clear.add_argument("--yes", action="store_true", help="Update cache.")
    clear.add_argument("--json", action="store_true", help="Emit JSON.")
    clear.set_defaults(func=cmd_clear)

    probe = sub.add_parser("probe", help="Probe provider health and cache it.")
    probe.add_argument("--role", default="", help="Only probe candidates for this role.")
    probe.add_argument("--ttl-sec", type=int, default=900, help="TTL in seconds.")
    probe.add_argument("--timeout", type=int, default=30, help="Timeout in seconds for each probe.")
    probe.add_argument("--json", action="store_true", help="Emit JSON.")
    probe.set_defaults(func=cmd_probe)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
