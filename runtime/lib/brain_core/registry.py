"""Реестр ролей и команд — машинный источник вместо таблиц в MEMORY.md.

MEMORY.md совмещала конституцию с реестрами: перечень тридцати ролей, таблицу
команд и матрицу эскалаций. Файл рос при добавлении любой роли, а цену платил
каждый запуск любого агента — 72% промпта уходило на текст, из которого агенту
нужны две строки.

Данные берутся оттуда, где они и так живут: frontmatter roles/*.md и teams/*.md.
Второго списка, который разойдётся с первым, не заводим.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_FM = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)


def _frontmatter(text: str) -> dict[str, str]:
    m = _FM.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def _as_list(value: str) -> list[str]:
    value = (value or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [v.strip().strip("'\"") for v in value.split(",") if v.strip()]


def _purpose(text: str) -> str:
    """Назначение роли — первая содержательная строка после заголовка."""
    body = _FM.sub("", text)
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line.rstrip(".")
    return ""


def load_roles(brain: Path) -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = {}
    for path in sorted((brain / "roles").glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = _frontmatter(text)
        roles[path.stem] = {
            "purpose": _purpose(text),
            "model_tier": fm.get("model_tier", ""),
            "doctrine": _as_list(fm.get("doctrine", "")),
            "writes": _as_list(fm.get("writes", "")),
        }
    return roles


def load_teams(brain: Path) -> dict[str, list[str]]:
    teams: dict[str, list[str]] = {}
    for path in sorted((brain / "teams").glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = _frontmatter(text)
        value = fm.get("roles", "")
        if not value:
            m = re.search(r"^roles:\s*(.+)$", text, re.M)
            value = m.group(1) if m else ""
        teams[path.stem] = _as_list(value)
    return teams


def role_brief(brain: Path, role: str) -> str:
    """Строки реестра, относящиеся к одной роли. Это и попадает в промпт.

    Агенту нужны его собственная запись, команды, в которые он входит, и зоны
    эскалации, где он назван, — а не весь реестр.
    """
    roles = load_roles(brain)
    entry = roles.get(role)
    lines: list[str] = []
    if entry:
        bits = [b for b in (entry["purpose"], f"модель: {entry['model_tier']}" if entry["model_tier"] else "") if b]
        lines.append(f"- Роль `{role}`: {'; '.join(bits) or 'описание в файле роли'}")
        if entry["writes"]:
            lines.append(f"- Пишет: {', '.join(entry['writes'])}")
    else:
        lines.append(f"- Роль `{role}` не описана в roles/ — работай по общим принципам")

    mates = {name: members for name, members in load_teams(brain).items() if role in members}
    for name, members in sorted(mates.items()):
        others = [m for m in members if m != role]
        lines.append(f"- Команда `{name}`: вместе с {', '.join(f'`{m}`' for m in others) or '(один)'}")

    zones = escalation_brief(brain, role)
    lines.extend(zones)
    return "\n".join(lines)


def escalation_brief(brain: Path, role: str) -> list[str]:
    """Зоны эскалации, где роль названа primary или адресатом эскалации."""
    path = brain / "doctrine" / "escalation-matrix.yaml"
    if not path.exists():
        return []
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return _escalation_brief_textual(path, role)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — матрица не должна ронять сборку промпта
        return []
    out: list[str] = []
    for section in ("zones", "tax_stages"):
        for entry in data.get(section) or []:
            primary = entry.get("primary") or []
            escalate = entry.get("escalate") or []
            if role in primary:
                tail = f", эскалация к {', '.join(escalate)}" if escalate else ""
                out.append(f"- Зона `{entry.get('id', '?')}`: ты primary{tail}")
            elif role in escalate:
                out.append(f"- Зона `{entry.get('id', '?')}`: подключают тебя, primary — {', '.join(primary)}")
    return out


def _escalation_brief_textual(path: Path, role: str) -> list[str]:
    """Запасной разбор без yaml: матрица важнее, чем наличие зависимости."""
    out: list[str] = []
    current = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m:
            current = m.group(1)
        if current and re.search(rf"\b{re.escape(role)}\b", line):
            if "primary" in line:
                out.append(f"- Зона `{current}`: ты primary")
            elif "escalate" in line:
                out.append(f"- Зона `{current}`: подключают тебя")
    return out
