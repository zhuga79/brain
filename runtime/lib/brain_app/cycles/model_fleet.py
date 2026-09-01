"""model-fleet: периодическая актуализация канонического списка живых моделей.

Дефект, который лечит цикл (t-2026-08-30-cyclical-model-list-actualizat):
агент предлагал устаревшие имена моделей (claude-sonnet-4-6), пока в
эксплуатации уже появлялись более новые (claude-sonnet-5). Разовые репорты
в wiki (model-fleet-report.md от 2026-08-14) протухали, а машиночитаемого
реестра, на который агенты могли бы опереться, не было.

Цикл на расписании:
1. освежает кеш здоровья провайдеров (`brain-provider probe`);
2. перечисляет живые модели по клиентам (`list_client_models` — живая
   команда CLI, затем API, затем конфиг);
3. снимает статус ролей (`brain-provider status`);
4. атомарно переписывает канонический реестр `config/model-fleet.json`
   (machine-readable, его читают агенты и lint);
5. переписывает человекочитаемый `wiki/model-fleet-report.md` — но только
   если страница не защищена курацией человека.

Отказ обновления не глотается: заводится corrective-задача, а вывод отказа
сохраняется в wiki/log.md. Это тот же контракт, что у validate/provider-probe.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from brain_core import clock, journal

from . import corrective, runner, systemd

NAME = "brain-model-fleet"
DEFAULT_AGENT = "model-fleet:cycle"
SOURCE = "model-fleet:refresh-failure"
REGISTRY_REL = Path("config") / "model-fleet.json"
REPORT_REL = Path("wiki") / "model-fleet-report.md"
STALE_AFTER_HOURS = 24.0

# Клиенты для перечисления моделей, когда в политике нет секции providers.
FALLBACK_CLIENTS = ("claude", "opencode", "codex")
TITLE_LIMIT = 70


def append_log(brain: Path, entry: str) -> None:
    journal.append_line(f"- {clock.utc_now()}: {entry}", brain)


def enabled_clients(matrix: dict[str, Any]) -> list[str]:
    """Провайдеры, за которые отвечает этот цикл: включённые в политике."""
    providers = matrix.get("providers") or {}
    clients = [name for name, cfg in providers.items() if cfg.get("enabled")]
    if not clients:
        clients = list(FALLBACK_CLIENTS)
    return clients


def discover_clients(brain: Path, clients: list[str]) -> dict[str, dict[str, Any]]:
    """Живые модели по каждому клиенту (cli → api → конфиг)."""
    from brain_provider import list_client_models

    result: dict[str, dict[str, Any]] = {}
    for client in clients:
        try:
            payload = list_client_models(brain, client, timeout=10)
        except Exception as exc:  # pragma: no cover — сеть отказов шире перечисленного
            payload = {"ok": False, "client": client, "available": False, "version": "",
                       "models": [], "source": "error", "error": str(exc)}
        result[client] = {
            "available": payload.get("available", False),
            "version": payload.get("version", ""),
            "models": payload.get("models", []),
            "source": payload.get("source", ""),
        }
    return result


def get_role_status(brain: Path) -> tuple[dict[str, dict[str, str]], str | None]:
    """Роли → {preferred key, model, status} из stdout brain-provider status."""
    try:
        proc = subprocess.run(
            ["brain-provider", "status", "--json"], cwd=str(brain),
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            return {}, f"'brain-provider status' failed: {proc.stderr.strip()}"
        data = json.loads(proc.stdout)
    except FileNotFoundError:
        return {}, "'brain-provider' command not found."
    except subprocess.TimeoutExpired:
        return {}, "'brain-provider status' timed out."
    except json.JSONDecodeError as exc:
        return {}, f"Failed to parse 'brain-provider status' JSON: {exc}"

    roles: dict[str, dict[str, str]] = {}
    for role, info in (data.get("roles") or {}).items():
        preferred = info.get("preferred") or {}
        if not isinstance(preferred, dict):
            continue
        roles[role] = {
            "preferred": str(preferred.get("key") or info.get("key") or ""),
            "model": str(preferred.get("model") or ""),
            "status": str(preferred.get("status") or info.get("cached_status") or ""),
        }
    return roles, None


def build_registry(
    clients: dict[str, dict[str, Any]],
    roles: dict[str, dict[str, str]],
    policy: str,
) -> dict[str, Any]:
    """Канонический реестр: в одном месте собранные живые модели и статусы ролей."""
    live: list[str] = []
    normalized: dict[str, dict[str, Any]] = {}
    for client, info in sorted(clients.items()):
        models = list(info.get("models") or [])
        prefixed = [
            m if m.startswith(f"{client}/") else f"{client}/{m}"
            for m in models
            if m and (not m.startswith("/"))
        ]
        live.extend(prefixed)
        normalized[client] = {
            "available": info.get("available", False),
            "version": info.get("version", ""),
            "models": prefixed,
            "source": info.get("source", ""),
        }

    seen: set[str] = set()
    live_model_ids = [m for m in live if not (m in seen or seen.add(m))]

    return {
        "version": 1,
        "updated_utc": clock.utc_now(),
        "stale_after_hours": STALE_AFTER_HOURS,
        "policy": policy,
        "clients": normalized,
        "roles": {role: dict(info) for role, info in sorted(roles.items())},
        "live_model_ids": live_model_ids,
    }


def registry_path(brain: Path) -> Path:
    return brain / REGISTRY_REL


def write_registry(brain: Path, registry: dict[str, Any]) -> Path:
    path = registry_path(brain)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def render_report(registry: dict[str, Any]) -> str:
    lines = [
        "# Model Fleet Report",
        "",
        f"**Обновлено:** {registry['updated_utc']} (`{NAME}`)",
        f"**Реестр:** `{REGISTRY_REL.as_posix()}`",
        f"**Политика:** `{registry.get('policy') or ''}`",
        f"**Устаревает через:** {registry.get('stale_after_hours')} ч",
        "",
        "## Клиенты и их модели",
        "",
        "| Клиент | Доступен | Источник | Версия | Модели |",
        "|---|---|---|---|---|",
    ]
    clients = registry.get("clients") or {}
    for client in sorted(clients):
        info = clients[client]
        models = "<br>".join(info.get("models") or []) or "—"
        if len(models) > 400:
            models = models[:397] + "..."
        lines.append(
            f"| {client} | {'да' if info.get('available') else 'нет'} | "
            f"{info.get('source') or '—'} | {info.get('version') or '—'} | {models} |"
        )
    lines += [
        "",
        "## Роли → preferred",
        "",
        "| Роль | Preferred | Модель | Статус |",
        "|---|---|---|---|",
    ]
    roles = registry.get("roles") or {}
    if not roles:
        lines.append("| — | — | — | — |")
    for role in sorted(roles):
        info = roles[role]
        lines.append(
            f"| {role} | {info.get('preferred') or '—'} | {info.get('model') or '—'} | "
            f"{info.get('status') or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(brain: Path, registry: dict[str, Any]) -> tuple[bool, str]:
    """Переписать wiki/model-fleet-report.md, уважая защиту страницы."""
    from brain_wiki.frontmatter import format_frontmatter, parse_frontmatter
    from brain_wiki.pages import existing_page_is_protected, read_text, today, write_text

    path = brain / REPORT_REL
    created = today()
    if path.exists():
        old_fm, _body = parse_frontmatter(read_text(path))
        if existing_page_is_protected(old_fm):
            return False, "wiki/model-fleet-report.md is human-curated/protected — skipped"
        created = str(old_fm.get("created") or created)

    fm = {
        "title": "Model Fleet Report — live models registry",
        "type": "concept",
        "created": created,
        "updated": today(),
        "curation": "agent",
        "protected": False,
        "source_policy": "advisory",
        "tags": ["providers", "health", "routing", "sre"],
        "sources": [],
        "related": [],
    }
    write_text(path, format_frontmatter(fm, render_report(registry)))
    return True, str(path.relative_to(brain))


_CORRECTIVE = corrective.Corrective(
    title="Refresh model fleet registry",
    source=SOURCE,
    role="sre",
    priority="P1",
    slug="model-fleet-refresh-fix",
    acceptance=(
        "`brain-model-fleet --apply` exits 0 and writes `config/model-fleet.json` with a "
        "fresh `updated_utc`; the refresh failure output is preserved in wiki/log.md so the "
        "'diagnosed' claim rests on recorded state, not on memory."
    ),
    ref="wiki/log.md",
)


def append_corrective_task(brain: Path) -> tuple[bool, str]:
    added = corrective.append(brain, [_CORRECTIVE])
    if not added:
        return False, f"Corrective task with source '{SOURCE}' already exists. Skipping."
    return True, f"Appended corrective task {added[0]} (source '{SOURCE}')."


def refresh_health_cache(brain: Path) -> str | None:
    """Освежить кеш здоровья провайдеров; вернуть текст отказа или None."""
    try:
        proc = subprocess.run(
            ["brain-provider", "probe", "--json", "--ttl-sec", "90"], cwd=str(brain),
            capture_output=True, text=True, timeout=90, check=False,
        )
    except FileNotFoundError:
        return "'brain-provider' command not found for probe."
    except subprocess.TimeoutExpired:
        return "'brain-provider probe' timed out."
    if proc.returncode != 0:
        return "'brain-provider probe' failed: " + (proc.stderr or proc.stdout or "").strip()[-500:]
    return None


def run_cycle(brain: Path, *, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "dry-run" if dry_run else "apply"}

    matrix: dict[str, Any] = {}
    from brain_provider import load_provider_matrix

    try:
        matrix = load_provider_matrix(brain)
    except Exception as exc:  # pragma: no cover
        result.setdefault("warnings", []).append(f"policy read warning: {exc}")

    failure_details: list[str] = []
    if not dry_run:
        probe_error = refresh_health_cache(brain)
        if probe_error:
            failure_details.append(probe_error)

    clients = discover_clients(brain, enabled_clients(matrix))
    roles, status_error = get_role_status(brain)
    if status_error:
        failure_details.append(status_error)

    registry = build_registry(
        clients,
        roles,
        policy=str(matrix.get("source") or "config/routing.json"),
    )
    result["registry"] = registry

    if failure_details:
        result["status"] = "error"
        result["message"] = "; ".join(failure_details)
        result["details"] = failure_details
        result["exit_code"] = 1
        if not dry_run:
            append_log(brain, f"{NAME}: FAILED - {'; '.join(failure_details)}")
            created, message = append_corrective_task(brain)
            result["task_created"] = created
            result["task_message"] = message
        return result

    if not dry_run:
        write_registry(brain, registry)
        report_ok, report_msg = write_report(brain, registry)
        result["report_written"] = report_ok
        result["report_message"] = report_msg
        append_log(brain, f"{NAME}: OK - registry updated ({len(registry['live_model_ids'])} live ids).")

    result["status"] = "success"
    result["exit_code"] = 0
    return result


def run(args: argparse.Namespace) -> int:
    brain = runner.resolve_brain(args)
    if not brain.is_dir():
        sys.stderr.write(f"Error: Brain path not found at '{brain}'. Is BRAIN_PATH set correctly?\n")
        return 1

    result = run_cycle(brain, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Message: {result.get('message', 'N/A')}")
        if result.get("details"):
            for detail in result["details"]:
                print(f"  - {detail}")
        for label, key in (
            ("Task", "task_message"),
            ("Report", "report_message"),
        ):
            if result.get(key):
                print(f"{label}: {result[key]}")
    return int(result.get("exit_code", 1))


def unit(args: argparse.Namespace) -> systemd.UnitSpec:
    brain = runner.resolve_brain(args)
    return systemd.UnitSpec(
        name=NAME,
        service_description="Refresh the canonical live-model registry and fleet report",
        timer_description="Run brain-model-fleet daily",
        command=systemd.resolve_command(NAME),
        exec_args=["--brain", str(brain), "--apply"],
        timer_options=[("OnCalendar", "daily"), ("RandomizedDelaySec", "15m"), ("Persistent", "true")],
        unit_options=[("Wants", f"{NAME}.timer")],
        working_dir=brain,
        environment=runner.service_environment(brain),
    )


SPEC = runner.CycleSpec(
    name=NAME,
    description="Refresh the canonical live-model registry and fleet report from probe results.",
    install_description="Install the brain-model-fleet user systemd timer.",
    run=run,
    unit=unit,
    default_agent=DEFAULT_AGENT,
    mode_required=True,
)