"""Provider/model routing matrix and lightweight health read model."""

from __future__ import annotations

import json
import datetime as dt
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


MATRIX_VERSION = 2
"""Версия формата конфигурации маршрутизации.

Поднята до 2 вместе с переездом в config/routing.json: у ролей появились
секции providers (решение оператора о доступности) и defaults.
"""


def _candidate(rank: int, provider: str, model: str, effort: str, command: str, use_for: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "rank": rank,
        "provider": provider,
        "model": model,
        "command": command,
        "use_for": use_for,
    }
    if effort:
        item["effort"] = effort
    return item


# Bootstrap-минимум, а не копия политики. Раньше здесь лежала четвёртая
# независимая версия маршрутизации (6 ролей против 9 в файле), и они
# расходились. Реальная политика живёт в config/routing.json; без него
# система обязана сказать об этом, а не тихо работать по вшитому списку.
DEFAULT_MATRIX: dict[str, Any] = {
    "version": MATRIX_VERSION,
    "updated": "",
    "source": "runtime-default",
    "manual_override_priority": [
        "explicit task/role override",
        "$BRAIN/config/routing.json",
        "runtime default matrix",
    ],
    "health_policy": {
        "live_probe_default": False,
        "reason": "provider probes can consume quota; dashboard reads config and cached status only",
        "cache_file": ".provider-health.json",
    },
    "defaults": {"cli": "claude"},
    "roles": {},
}


def matrix_path(brain: Path) -> Path:
    """Файл политики маршрутизации.

    Лежит в config/, а не в wiki/: wiki — слой знаний, который курирует
    человек и который brain-publish отдаёт наружу как контент. Конфигурация
    исполнения там быть не должна.

    Старое расположение поддерживается как фолбэк, чтобы дерево, не прошедшее
    миграцию, продолжало работать.
    """
    new = brain / "config" / "routing.json"
    if new.exists():
        return new
    legacy = brain / "wiki" / "provider-matrix.json"
    return legacy if legacy.exists() else new


def health_path(brain: Path) -> Path:
    return brain / ".provider-health.json"


def load_provider_matrix(brain: Path) -> dict[str, Any]:
    """Load matrix from Brain wiki, falling back to runtime defaults."""
    path = matrix_path(brain)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("source", str(path))
            return data
        except (OSError, json.JSONDecodeError) as exc:
            fallback = json.loads(json.dumps(DEFAULT_MATRIX))
            fallback["source"] = "runtime-default"
            fallback["warning"] = f"invalid matrix file: {exc}"
            return fallback
    # Конфига нет: возвращаем bootstrap-минимум, но говорим об этом. Молча
    # отдать пустой список ролей значит выдать «маршрутизация не настроена»
    # за «маршрутизация такая».
    fallback = json.loads(json.dumps(DEFAULT_MATRIX))
    fallback["warning"] = (
        f"нет файла маршрутизации {brain / 'config' / 'routing.json'} — "
        "роли не настроены, используется только defaults.cli"
    )
    return fallback


def load_provider_health(brain: Path) -> dict[str, Any]:
    """Load cached provider health without contacting providers."""
    path = health_path(brain)
    if not path.exists():
        return {"source": "", "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("source", str(path))
            data.setdefault("items", {})
            return data
    except (OSError, json.JSONDecodeError) as exc:
        return {"source": str(path), "items": {}, "warning": f"invalid health cache: {exc}"}
    return {"source": str(path), "items": {}, "warning": "health cache must be a JSON object"}


def collect_provider_status(brain: Path) -> dict[str, Any]:
    """Return role matrix with preferred/fallback/unavailable status.

    This function is intentionally read-only and does not probe remote APIs.
    Availability is derived from local command presence plus optional cached
    health records in ``$BRAIN/.provider-health.json``.
    """
    matrix = load_provider_matrix(brain)
    health = load_provider_health(brain)
    out_roles: dict[str, Any] = {}
    for role in matrix.get("roles", {}):
        candidates, profile = role_candidates(matrix, role)
        # Провайдер, выключенный оператором, идёт в unavailable наравне с
        # неотвечающим: для потребителя статуса это одно и то же — кандидат
        # сейчас не будет выбран, и видно, почему.
        enriched = []
        for cand in sorted(candidates, key=lambda c: c.get("rank", 99)):
            item = _enrich_candidate({**cand, "command": candidate_command(matrix, cand)}, health)
            allowed, why = provider_enabled(matrix, str(cand.get("provider", "")))
            if not allowed:
                item["status"] = "unavailable"
                item["reason"] = why
            enriched.append(item)
        available = [c for c in enriched if c["status"] not in UNHEALTHY_STATUSES]
        preferred = available[0] if available else None
        out_roles[role] = {
            "profile": profile,
            "preferred": preferred,
            "fallback": available[1:],
            "unavailable": [c for c in enriched if c["status"] in UNHEALTHY_STATUSES],
            "candidates": enriched,
        }
    return {
        "version": matrix.get("version", MATRIX_VERSION),
        "updated": matrix.get("updated", ""),
        "source": matrix.get("source", str(matrix_path(brain)) if matrix_path(brain).exists() else "runtime-default"),
        "warning": matrix.get("warning", ""),
        "manual_override_priority": matrix.get("manual_override_priority", []),
        "health_policy": matrix.get("health_policy", {}),
        "health_source": health.get("source", ""),
        "health_warning": health.get("warning", ""),
        "roles": out_roles,
        "profiles": matrix.get("profiles", {}),
        "providers": matrix.get("providers", {}),
        "routes": matrix.get("routes", {}),
    }


# --- список доступных моделей по CLI (для формы ручного запуска) ---

# CLI с командой живого списка моделей
_LIVE_MODEL_COMMANDS: dict[str, list[str]] = {
    "ollama": ["ollama", "list"],
    "opencode": ["opencode", "models"],
}

# известные алиасы, которых нет в матрице
_STATIC_MODELS: dict[str, list[str]] = {
    "claude": ["opus", "sonnet", "haiku"],
}

_MODELS_CACHE_TTL_SECONDS = 300
_models_cache: dict[str, tuple[float, dict[str, Any]]] = {}


UNHEALTHY_STATUSES = ("unavailable", "rate-limited", "model-not-found", "quota-exhausted", "error")
"""Состояния, при которых кандидат не берётся: провайдер не ответит или откажет."""

DEFAULT_CLI = "claude"


def provider_enabled(matrix: dict[str, Any], provider: str) -> tuple[bool, str]:
    """Разрешён ли провайдер решением оператора.

    Отличается от здоровья: здоровье — это «сейчас не отвечает», а enabled —
    «не использовать, даже если отвечает». Так gemini выключается одной
    правкой конфигурации, а не вычёркиванием из девяти списков ролей.
    """
    entry = (matrix.get("providers") or {}).get(provider)
    if not isinstance(entry, dict):
        return True, ""
    if entry.get("enabled", True):
        return True, ""
    return False, str(entry.get("reason") or entry.get("note") or "отключён в config/routing.json")


def default_cli(matrix: dict[str, Any]) -> str:
    return str((matrix.get("defaults") or {}).get("cli") or DEFAULT_CLI)


def candidate_command(matrix: dict[str, Any], candidate: dict[str, Any]) -> str:
    """Команда кандидата: своя, либо собранная из описания провайдера.

    В профилях кандидат — это «провайдер плюс модель», а как именно передать
    модель, знает провайдер. Иначе строка запуска дублировалась бы в каждом из
    двенадцати профилей, и опечатка в одной из них ловилась бы только запуском.
    """
    explicit = str(candidate.get("command", "")).strip()
    if explicit:
        return explicit
    provider = str(candidate.get("provider", ""))
    entry = (matrix.get("providers") or {}).get(provider) or {}
    base = str(entry.get("command", "") or provider).strip()
    model = str(candidate.get("model", "")).strip()
    flag = str(entry.get("model_flag", "")).strip()
    if model and flag:
        return f"{base} {flag.format(model=model)}".strip()
    return base


def role_candidates(matrix: dict[str, Any], role: str) -> tuple[list[dict[str, Any]], str]:
    """Кандидаты роли и имя её профиля.

    Роль указывает профиль, профиль — упорядоченный список кандидатов. Список
    прямо в роли тоже принимается: так записаны деревья до перехода на профили.
    """
    roles = matrix.get("roles") or {}
    entry = roles.get(role)
    if entry is None and "-" in role:
        entry = roles.get(role.replace("-", "_"))
    if isinstance(entry, list):
        return entry, ""
    if isinstance(entry, dict):
        profile = str(entry.get("profile", ""))
        if profile:
            return list((matrix.get("profiles") or {}).get(profile) or []), profile
        return list(entry.get("candidates") or []), ""
    return [], ""


def role_profile(matrix: dict[str, Any], role: str) -> str:
    return role_candidates(matrix, role)[1]


def _pinned_client(brain: Path, role: str, task: str) -> str:
    """Клиент, закреплённый скиллом за парой роль+задача. Пусто, если нет."""
    if os.environ.get("BRAIN_DISABLE_SKILL_ROUTING") == "1" or not task:
        return ""
    try:
        from brain_skill_parser import get_pinned_client_for_task_role
    except ImportError:
        return ""
    try:
        return (get_pinned_client_for_task_role(role, task, brain) or "").strip()
    except Exception:
        # Закрепление — подсказка, а не обязательство: сломанный скилл не
        # должен мешать запуску роли.
        return ""


def resolve_for_role(
    brain: Path,
    role: str,
    task: str = "",
    not_provider: str = "",
    override: str = "",
    author_provider: str = "",
) -> dict[str, Any]:
    """Команда запуска для роли. Единственное место, где решается порядок.

    Приоритет: явный override (--cli / BRAIN_CLI_OVERRIDE) → закрепление
    скиллом → конфигурация маршрутизации → defaults.cli. Раньше этот порядок
    был записан дважды и по-разному: bash-строка `cli_for_<role>` не знала ни
    рангов, ни здоровья, поэтому у brain-launch и brain-council fallback не
    было вовсе, а brain-orchestrator шеллаутил в тот же файл, уже имея на
    руках разобранную матрицу.

    `not_provider` исключает провайдера — этим пользуется правило
    диверсификации: ревьюер не должен идти к тому же провайдеру, что автор.

    Возвращает словарь: command, provider, model, source, reason, warnings.
    Команда есть всегда: не найдя кандидата, резолвер отдаёт defaults.cli и
    пишет причину в warnings. Отказ запускать роль хуже запуска на дефолте.
    """
    matrix = load_provider_matrix(brain)
    warnings: list[str] = []
    if matrix.get("warning"):
        warnings.append(str(matrix["warning"]))
    fallback_cli = default_cli(matrix)

    if override:
        return {"command": override, "provider": "", "model": "", "source": "override",
                "reason": "явное указание клиента", "warnings": warnings}

    pinned = _pinned_client(brain, role, task)
    if pinned:
        return {"command": pinned, "provider": pinned, "model": "", "source": "skill-pin",
                "reason": f"клиент закреплён скиллом за задачей {task}", "warnings": warnings}

    candidates, profile = role_candidates(matrix, role)

    # Правило диверсификации из MEMORY.md: рецензент и арбитр не должны идти к
    # тому же провайдеру, что автор, иначе слепые пятна коррелируют и ревью
    # ничего не ловит. Раньше правило исполнялось руками и было захардкожено
    # одной строкой для reviewer; теперь роль помечена в конфигурации, а
    # провайдера автора сообщает вызывающий.
    entry = (matrix.get("roles") or {}).get(role)
    if not isinstance(entry, dict):
        entry = {}
    if not not_provider and author_provider and entry.get("diversify_from_author"):
        not_provider = author_provider

    health = load_provider_health(brain)
    skipped: list[str] = []
    for cand in sorted(candidates, key=lambda c: c.get("rank", 99)):
        provider = str(cand.get("provider", ""))
        command = candidate_command(matrix, cand)
        if not command:
            continue
        if not_provider and provider == not_provider:
            skipped.append(f"{provider}: исключён правилом диверсификации")
            continue
        allowed, why = provider_enabled(matrix, provider)
        if not allowed:
            skipped.append(f"{provider}: {why}")
            continue
        enriched = _enrich_candidate({**cand, "command": command}, health)
        if enriched["status"] in UNHEALTHY_STATUSES:
            skipped.append(f"{enriched['key']}: {enriched['status']} — {enriched['reason']}")
            continue
        return {
            "command": command,
            "provider": provider,
            "model": str(cand.get("model", "")),
            "profile": profile,
            "source": "config",
            "reason": enriched["reason"],
            "skipped": skipped,
            "warnings": warnings,
        }

    if candidates and not_provider:
        # Отфильтровали всё — запуск важнее чистоты правила: без ревью хуже,
        # чем с ревью у того же провайдера. Но об этом надо сказать.
        relaxed = resolve_for_role(brain, role, task=task, override=override)
        if relaxed["source"] == "config":
            relaxed["warnings"] = list(relaxed.get("warnings") or []) + [
                f"роль {role}: правило диверсификации отменено — кроме {not_provider} "
                "доступных кандидатов нет"
            ]
            relaxed["diversify_relaxed"] = True
            return relaxed
    if candidates:
        warnings.append(f"роль {role}: ни один кандидат не доступен ({'; '.join(skipped)})")
    elif not matrix.get("warning"):
        warnings.append(f"роль {role} не описана в {matrix_path(brain)}")
    return {"command": fallback_cli, "provider": "", "model": "", "profile": profile,
            "source": "default", "reason": "кандидат не найден, используется defaults.cli",
            "skipped": skipped, "warnings": warnings}


def matrix_models_for_client(matrix: dict[str, Any], client: str) -> list[str]:
    """Модели, сконфигурированные для CLI (профили, роли, устаревшие routes)."""
    models: list[str] = []
    groups = list((matrix.get("profiles") or {}).values())
    # Роль может нести список кандидатов напрямую — так записаны деревья,
    # не перешедшие на профили.
    groups += [v for v in (matrix.get("roles") or {}).values() if isinstance(v, list)]
    for candidates in groups:
        for cand in candidates or []:
            if str(cand.get("provider") or "") == client and cand.get("model"):
                models.append(str(cand["model"]))
    for chain in (matrix.get("routes") or {}).values():
        for entry in chain or []:
            provider, _, model = str(entry).partition("/")
            if provider == client and model:
                models.append(model)
    return models


def _parse_live_models(client: str, stdout: str) -> list[str]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    models: list[str] = []
    if client == "ollama":
        for line in lines:
            if line.lower().startswith("name"):
                continue  # заголовок таблицы
            models.append(line.split()[0])
    elif client == "opencode":
        for line in lines:
            if line.startswith(("-", "=", "#")):
                continue
            models.append(line.split()[0])
    return models


def _http_get_json(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        data = json.loads((Path.home() / ".codex" / "auth.json").read_text(encoding="utf-8"))
        return str(data.get("OPENAI_API_KEY") or "").strip()
    except (OSError, json.JSONDecodeError):
        return ""


def _anthropic_auth_headers() -> dict[str, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        data = json.loads((Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        token = str((data.get("claudeAiOauth") or {}).get("accessToken") or "").strip()
    except (OSError, json.JSONDecodeError):
        token = ""
    if token:
        return {
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
        }
    return {}


def _gemini_api_key() -> str:
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return key
    return ""


_OPENAI_MODEL_EXCLUDE = re.compile(
    r"embedding|audio|tts|whisper|dall-e|image|moderation|realtime|transcribe|search"
)


def _api_models(client: str, timeout: int = 10) -> list[str]:
    """Актуальные модели из API провайдера (если есть локальные учётные данные)."""
    try:
        if client == "codex":
            key = _openai_api_key()
            if not key:
                return []
            data = _http_get_json(
                "https://api.openai.com/v1/models",
                {"Authorization": f"Bearer {key}"}, timeout,
            )
            ids = [str(m.get("id") or "") for m in data.get("data") or []]
            return sorted(
                i for i in ids
                if (i.startswith(("gpt-", "codex")) or re.match(r"^o\d", i))
                and not _OPENAI_MODEL_EXCLUDE.search(i)
            )
        if client == "claude":
            headers = _anthropic_auth_headers()
            if not headers:
                return []
            data = _http_get_json("https://api.anthropic.com/v1/models?limit=100", headers, timeout)
            return [str(m.get("id") or "") for m in data.get("data") or [] if m.get("id")]
        if client == "gemini":
            key = _gemini_api_key()
            if not key:
                return []
            data = _http_get_json(
                f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}",
                {}, timeout,
            )
            models = []
            for m in data.get("models") or []:
                name = str(m.get("name") or "").split("/")[-1]
                methods = m.get("supportedGenerationMethods") or []
                if name and ("generateContent" in methods or not methods):
                    models.append(name)
            return models
    except Exception:  # сеть/авторизация/формат — тихий фолбэк на конфиг
        return []
    return []


def _probe_client_version(client: str, timeout: int = 8) -> str:
    """Вызвать `<cli> --version` и вернуть первую строку вывода ('' при неудаче)."""
    try:
        result = subprocess.run(
            [client, "--version"], capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    out = (result.stdout or result.stderr or "").strip()
    return out.splitlines()[0].strip() if out else ""


def list_client_models(brain: Path, client: str, timeout: int = 10) -> dict[str, Any]:
    """Проверить доступность CLI (бинарник + `--version`) и получить актуальные
    модели: живым вызовом CLI, если он умеет перечислять модели, иначе —
    из провайдерской матрицы + известных алиасов. Кэш 5 мин."""
    cached = _models_cache.get(client)
    now = time.time()
    if cached and now - cached[0] < _MODELS_CACHE_TTL_SECONDS:
        return cached[1]

    binary_path = shutil.which(client)
    available = bool(binary_path)
    version = _probe_client_version(client, timeout=timeout) if available else ""

    models: list[str] = []
    source = "config"
    cmd = _LIVE_MODEL_COMMANDS.get(client)
    if available and cmd:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                models = _parse_live_models(client, result.stdout)
                if models:
                    source = "live"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not models:
        models = _api_models(client, timeout=timeout)
        if models:
            source = "api"
    if not models:
        matrix = load_provider_matrix(brain)
        models = matrix_models_for_client(matrix, client) + _STATIC_MODELS.get(client, [])

    seen: set[str] = set()
    unique = [m for m in models if not (m in seen or seen.add(m))]
    payload = {
        "ok": True,
        "client": client,
        "available": available,
        "version": version,
        "binary": binary_path or "",
        "models": unique,
        "source": source,
    }
    _models_cache[client] = (now, payload)
    return payload


def _enrich_candidate(candidate: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    item = dict(candidate)
    command = str(item.get("command", "")).strip()
    executable = command.split()[0] if command else ""
    command_present = bool(executable and shutil.which(executable))
    key = f"{item.get('provider', '')}/{item.get('model', '')}"
    health_item = health.get("items", {}).get(key, {})
    cached_status = str(health_item.get("status", "")).strip()
    checked_at_str = health_item.get("checked_at")
    
    is_within_ttl = False
    if checked_at_str:
        # Support both "...Z" and "...+00:00" ISO formats
        try:
            checked_at = dt.datetime.fromisoformat(checked_at_str.replace("Z", "+00:00"))
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            checked_at = None
        if checked_at is not None:
            ttl = health_item.get("ttl_seconds", 900)
            if (dt.datetime.now(dt.timezone.utc) - checked_at).total_seconds() <= ttl:
                is_within_ttl = True

    if checked_at_str:
        if is_within_ttl:
            if cached_status == "available":
                status = "healthy"
            elif cached_status in ("unavailable", "rate-limited", "model-not-found", "quota-exhausted", "error"):
                status = cached_status
            else:
                status = cached_status
        else:
            status = "stale"
        reason = str(health_item.get("reason", "cached health")).strip()
    else:
        status = "unknown"
        reason = "local command found" if command_present else "command not found"

    item["key"] = key
    item["command_present"] = command_present
    item["status"] = status
    item["reason"] = reason
    if checked_at_str:
        item["checked_at"] = checked_at_str
        item["cached_status"] = cached_status
    return item

DOC_BEGIN = "<!-- routing:begin -->"
DOC_END = "<!-- routing:end -->"


def render_routing_doc(brain: Path) -> str:
    """Человекочитаемая проекция конфигурации маршрутизации.

    Проза страницы держала собственные списки приоритетов и разошлась с
    машинным источником по пяти ролям из шести — сравнить их можно было только
    глазами, и никто не сравнивал. Блок между маркерами генерируется, всё
    остальное на странице остаётся человеческим текстом.
    """
    matrix = load_provider_matrix(brain)
    profiles = matrix.get("profiles") or {}
    roles = matrix.get("roles") or {}
    providers = matrix.get("providers") or {}

    lines = [DOC_BEGIN, "", "_Блок сгенерирован из `config/routing.json` — правь конфигурацию, не текст._", ""]

    off = [f"`{name}` — {entry.get('note') or entry.get('reason') or 'отключён'}"
           for name, entry in sorted(providers.items())
           if isinstance(entry, dict) and not entry.get("enabled", True)]
    if off:
        lines += ["**Провайдеры вне игры:** " + "; ".join(off), ""]

    by_profile: dict[str, list[str]] = {}
    for role, entry in sorted(roles.items()):
        profile = entry.get("profile", "") if isinstance(entry, dict) else ""
        by_profile.setdefault(profile or "(без профиля)", []).append(role)

    lines += ["| Профиль | Роли | Порядок кандидатов |", "|---|---|---|"]
    for profile, names in sorted(by_profile.items()):
        chain = []
        for cand in sorted(profiles.get(profile) or [], key=lambda c: c.get("rank", 99)):
            model = str(cand.get("model") or "")
            label = f"{cand.get('provider', '?')}/{model}" if model else str(cand.get("provider", "?"))
            if cand.get("effort"):
                label += f" ({cand['effort']})"
            chain.append(label)
        diversify = any(
            isinstance(roles.get(n), dict) and roles[n].get("diversify_from_author")
            for n in names
        )
        mark = " ⇄" if diversify else ""
        lines.append(f"| `{profile}`{mark} | {', '.join(f'`{n}`' for n in names)} | {' → '.join(chain) or '—'} |")

    lines += ["", "⇄ — роль не идёт к провайдеру автора работы (правило диверсификации).", "", DOC_END]
    return "\n".join(lines)


def project_routing_doc(brain: Path, page: Path) -> tuple[str, bool]:
    """Вставить сгенерированный блок в страницу. Возвращает (текст, изменился)."""
    text = page.read_text(encoding="utf-8") if page.exists() else ""
    block = render_routing_doc(brain)
    if DOC_BEGIN in text and DOC_END in text:
        head = text.split(DOC_BEGIN)[0]
        tail = text.split(DOC_END, 1)[1]
        new = head + block + tail
    else:
        new = text.rstrip("\n") + "\n\n" + block + "\n"
    return new, new != text
