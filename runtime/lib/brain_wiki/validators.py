"""Validation logic for Brain wiki pages, raw sources, and UI/UX skill pack.

All public functions return a list[Issue]. Validators are intentionally
read-only: they report problems but never modify files.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from brain_core.paths import iter_system_files, resolve_system_asset, system_asset_rel

from .frontmatter import as_list, parse_frontmatter, validate_date
from .pages import (
    Issue,
    all_page_slugs,
    extract_wikilinks,
    iter_wiki_pages,
    raw_ref_to_path,
    read_text,
    source_refs,
    extract_task_refs,
)

VALID_PAGE_TYPES = {"concept", "entity", "project", "source-summary", "decision"}
VALID_RAW_TYPES = {"article", "paper", "spec", "transcript", "doc", "note", "webpage"}
VALID_CURATION = {"human", "agent", "imported"}
VALID_SOURCE_POLICIES = {"advisory", "required", "ignored"}


REQUIRED_DIRS = ("raw", "wiki", "tasks")
EXPECTED_DIRS = ("roles", "doctrine", "prd", "teams", "council", ".locks")
EXPECTED_FILES = (
    "MEMORY.md",
    "tasks/active.md",
    "tasks/done.md",
    "wiki/index.md",
    "wiki/log.md",
)
# После раздела эти каталоги живут только в системном корне.
# Локальный оверрайд roles/teams/doctrine/skills — не восстановление.
EXCLUSIVE_SYSTEM_DIRS = ("runtime", "tests", "spec", "docs")


def validate_staged_write_path(brain: Path) -> list[Issue]:
    """Staged system files in the data repo when roots are split."""
    import subprocess

    from brain_core.layers import write_path_violations
    from brain_core.paths import brain_system_path

    if brain is None:
        return []
    root = Path(brain)
    try:
        staged = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACMR",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []
    system = brain_system_path(brain=root)
    return [
        Issue(
            "ERROR",
            path,
            "системный файл в дереве данных; правь веткой в BRAIN_SYSTEM_PATH",
        )
        for path in write_path_violations(
            staged, repo=root, data=root, system=system
        )
    ]


def validate_paths(brain: Path) -> list[Issue]:
    issues = []
    for d in REQUIRED_DIRS:
        if not (brain / d).is_dir():
            issues.append(Issue("ERROR", d + "/", "missing required directory"))
    for d in EXPECTED_DIRS:
        exists = (brain / d).is_dir() or resolve_system_asset(d, brain=brain).is_dir()
        if not exists:
            issues.append(Issue("WARN", d + "/", "expected directory missing"))
    for f in EXPECTED_FILES:
        if not (brain / f).exists():
            issues.append(Issue("WARN", f, "expected file missing"))
    return issues


def validate_raw_source(brain: Path, path: Path) -> list[Issue]:
    rel = str(path.relative_to(brain))
    fm, _body = parse_frontmatter(read_text(path))
    issues = []
    if not fm:
        return [Issue("ERROR", rel, "missing frontmatter")]
    for key in ("title", "type", "fetched"):
        if not fm.get(key):
            issues.append(Issue("ERROR", rel, f"missing frontmatter field {key}"))
    if fm.get("type") and str(fm["type"]) not in VALID_RAW_TYPES:
        issues.append(Issue("ERROR", rel, f"invalid raw type {fm['type']}"))
    if fm.get("fetched") and not validate_date(fm["fetched"]):
        issues.append(Issue("ERROR", rel, f"invalid fetched date {fm['fetched']}"))
    if fm.get("published") and not validate_date(fm["published"]):
        issues.append(Issue("WARN", rel, f"invalid published date {fm['published']}"))
    return issues


def validate_system_paths_not_restored(brain: Path) -> list[Issue]:
    """Запрет вернуть системный каталог в приватное дерево.

    Срабатывает только при двух корнях. Иначе раскладка «один корень»
    остаётся рабочей, и откат не ломается.
    """
    from brain_core.paths import brain_system_path

    system = brain_system_path(brain=brain)
    try:
        same_root = system.resolve() == Path(brain).resolve()
    except OSError:
        same_root = Path(system) == Path(brain)
    if same_root:
        return []

    issues: list[Issue] = []
    for name in EXCLUSIVE_SYSTEM_DIRS:
        if (brain / name).is_dir():
            issues.append(Issue(
                "ERROR",
                f"{name}/",
                "системный путь восстановлен в приватном дереве",
            ))
    return issues


def validate_wiki_page(brain: Path, path: Path, slugs: set[str] | None = None) -> list[Issue]:
    rel = str(path.relative_to(brain))
    slugs = slugs if slugs is not None else all_page_slugs(brain)
    fm, body = parse_frontmatter(read_text(path))
    issues = []
    if not fm:
        return [Issue("ERROR", rel, "missing frontmatter")]

    for key in ("title", "type", "created", "updated"):
        if not fm.get(key):
            issues.append(Issue("ERROR", rel, f"missing frontmatter field {key}"))

    page_type = str(fm.get("type", ""))
    if page_type and page_type not in VALID_PAGE_TYPES:
        issues.append(Issue("ERROR", rel, f"invalid page type {page_type}"))

    for key in ("created", "updated", "last_reviewed_at"):
        if fm.get(key) and not validate_date(fm[key]):
            issues.append(Issue("ERROR", rel, f"invalid {key} date {fm[key]}"))

    if fm.get("curation") and str(fm["curation"]) not in VALID_CURATION:
        issues.append(Issue("ERROR", rel, f"invalid curation {fm['curation']}"))
    if fm.get("source_policy") and str(fm["source_policy"]) not in VALID_SOURCE_POLICIES:
        issues.append(Issue("ERROR", rel, f"invalid source_policy {fm['source_policy']}"))

    sources = source_refs(fm)
    source_policy = str(fm.get("source_policy") or "advisory")
    if (page_type == "source-summary" or source_policy == "required") and not sources:
        issues.append(Issue("ERROR", rel, f"{page_type} pages with source_policy={source_policy} require sources"))
    for source in sources:
        source_path = raw_ref_to_path(brain, source)
        if not source_path.exists():
            issues.append(Issue("ERROR", rel, f"missing source {source}"))

    related_links = []
    for related in as_list(fm.get("related")):
        related_links.extend(extract_wikilinks(related) or [related])

    for link in sorted(set(extract_wikilinks(body) + related_links)):
        if link not in slugs:
            issues.append(Issue("ERROR", rel, f"broken wikilink [[{link}]]"))

    return issues


def validate_task_refs(brain: Path, path: Path, slugs: set[str]) -> list[Issue]:
    if not path.exists():
        return []
    rel = str(path.relative_to(brain))
    content = read_text(path)
    issues = []
    for ref_line, where in extract_task_refs(content):
        for link in extract_wikilinks(ref_line):
            if link not in slugs:
                issues.append(Issue("ERROR", rel, f"{where}: broken wikilink [[{link}]]"))
        for raw_ref in re.findall(r"raw/[^\s,\]]+\.md", ref_line):
            if not (brain / raw_ref).exists():
                issues.append(Issue("ERROR", rel, f"{where}: missing raw reference {raw_ref}"))
        for wiki_ref in re.findall(r"wiki/([^\s,\]]+)\.md", ref_line):
            if Path(wiki_ref).stem not in slugs:
                issues.append(Issue("ERROR", rel, f"{where}: missing wiki reference wiki/{wiki_ref}.md"))
    return issues


def validate_task_client_fields(brain: Path, path: Path) -> list[Issue]:
    """Warn when a task block sets project: without a client:.

    Заказчик — единица биллинга (часы и отчёты агрегируются по нему), проект —
    внутренняя единица организации работы. Проект без заказчика не попадает в
    биллинг и в агрегацию по клиентам на дашборде.
    """
    if not path.exists():
        return []
    # Разбор блока — общий, из brain_task_parser. Тихо пропустить проверку при
    # неудачном импорте нельзя: валидатор молчал бы ровно там, где не смотрел.
    import brain_task_parser

    rel = str(path.relative_to(brain))
    content = read_text(path)
    issues = []
    for block in brain_task_parser.find_blocks(content):
        info = brain_task_parser.parse_block(block)
        if not info:
            continue
        if info.get("project") and not info.get("client"):
            issues.append(Issue(
                "WARN", rel,
                f"{info.get('id', '?')}: project задан без client — проект без заказчика"
                " не попадёт в агрегацию по клиентам и биллинг",
            ))
    return issues


def validate_queue_scope(brain: Path, path: Path) -> list[Issue]:
    """Корневая очередь — очередь разработки Brain, дел клиентов в ней нет.

    Дело живёт в своей папке: там материалы, там же `TASKS.md` и `LOG.md`.
    Пока задачи дела стояли в общей очереди, разработка и работа по клиентам
    делили один список приоритетов, а персональные данные оседали в репозитории
    системы.

    Признак — поле `client:`: заказчик это единица биллинга, а биллинг бывает
    только у работы по делу. Задачу дела, у которой заказчик не проставлен,
    проверка не отличит от системной — это цена машинного признака.

    Проза, упоминающая `client:`, полем не считается: границу держит
    `brain_core.grammar.parse_fields`, на которую опирается разбор блока.
    """
    if not path.exists():
        return []
    import brain_task_parser

    rel = str(path.relative_to(brain))
    issues = []
    for block in brain_task_parser.find_blocks(read_text(path)):
        info = brain_task_parser.parse_block(block)
        if not info:
            continue
        client = info.get("client", "")
        if not client:
            continue
        issues.append(Issue(
            "ERROR", rel,
            f"{info.get('id', '?')}: клиентская задача в очереди разработки"
            f" (client: {client}) — перенеси в TASKS.md папки дела",
        ))
    return issues


def validate_index(brain: Path, slugs: set[str]) -> list[Issue]:
    index = brain / "wiki" / "index.md"
    if not index.exists():
        return []
    issues = []
    for link in extract_wikilinks(read_text(index)):
        if link not in slugs:
            issues.append(Issue("ERROR", "wiki/index.md", f"broken index wikilink [[{link}]]"))
    return issues


def validate_routing(brain: Path) -> list[Issue]:
    """Дыры в маршрутизации роль → команда.

    Раньше расхождение источников не ловилось ничем: роль без записи молча
    уходила в CLI_DEFAULT, ссылка на несуществующий профиль читалась как
    «кандидатов нет», а файл, оставшийся после миграции, продолжал
    перехватывать маршрут — и всё это выглядело как работающая система.
    """
    import json

    import brain_provider

    issues: list[Issue] = []
    role_files = iter_system_files("roles", "*.md", brain=brain)
    config = resolve_system_asset("config/routing.json", brain=brain)

    # Файлы, оставшиеся от прежних источников: пока они лежат на месте, они
    # участвуют в разрешении маршрута и тихо перебивают конфигурацию.
    for rel, why in (
        ("wiki/provider-matrix.json", "политика переехала в config/routing.json"),
        (".cli-mapping.sh", "bash-маршрутизация удалена, её читатели переведены на brain-provider cli"),
    ):
        stale = brain / rel if rel.startswith("wiki/") else resolve_system_asset(rel, brain=brain)
        if stale.exists():
            issues.append(Issue("ERROR", rel, f"остался после миграции: {why}"))

    if not config.exists():
        if role_files:
            issues.append(Issue("ERROR", "config/routing.json", "нет файла маршрутизации"))
        return issues

    try:
        matrix = json.loads(read_text(config))
    except (ValueError, OSError) as exc:
        return issues + [Issue("ERROR", "config/routing.json", f"не читается: {exc}")]
    if not isinstance(matrix, dict):
        return issues + [Issue("ERROR", "config/routing.json", "корень должен быть объектом")]

    version = matrix.get("version")
    if version != brain_provider.MATRIX_VERSION:
        issues.append(Issue("ERROR", "config/routing.json",
                            f"версия {version!r}, ожидается {brain_provider.MATRIX_VERSION}"))

    profiles = matrix.get("profiles") or {}
    providers = matrix.get("providers") or {}
    roles = matrix.get("roles") or {}

    for name, candidates in profiles.items():
        ranks = [c.get("rank") for c in candidates or []]
        if len(ranks) != len(set(ranks)):
            issues.append(Issue("ERROR", "config/routing.json",
                                f"профиль {name}: повторяющийся rank {sorted(ranks)}"))
        for cand in candidates or []:
            provider = str(cand.get("provider", ""))
            if provider not in providers:
                issues.append(Issue("ERROR", "config/routing.json",
                                    f"профиль {name}: провайдер {provider!r} не описан в providers"))

    for role, entry in roles.items():
        profile = entry.get("profile") if isinstance(entry, dict) else ""
        if profile and profile not in profiles:
            issues.append(Issue("ERROR", "config/routing.json",
                                f"роль {role}: профиль {profile!r} не существует"))

    for path in role_files:
        role = path.stem
        candidates, _ = brain_provider.role_candidates(matrix, role)
        if not candidates:
            issues.append(Issue("ERROR", f"roles/{path.name}",
                                "роль без разрешимой записи в config/routing.json — "
                                "запуск уйдёт в defaults.cli без модели"))

    # Проза страницы решения обязана совпадать с конфигурацией. Раньше она
    # держала собственные списки и разошлась по пяти ролям из шести — сравнить
    # можно было только глазами, и никто не сравнивал.
    doc = brain / "wiki" / "decision-llm-stack.md"
    if doc.exists():
        try:
            _, drifted = brain_provider.project_routing_doc(brain, doc)
        except Exception as exc:  # noqa: BLE001 — проекция не должна ронять валидатор
            issues.append(Issue("WARN", "wiki/decision-llm-stack.md",
                                f"не удалось спроецировать маршрутизацию: {exc}"))
        else:
            if drifted:
                issues.append(Issue(
                    "ERROR", "wiki/decision-llm-stack.md",
                    "блок маршрутизации разошёлся с config/routing.json — "
                    "обнови командой brain-provider render-doc"))

    # Предупреждение, а не ошибка: CLI может быть не установлен на этой машине,
    # но записан как рабочий вариант для другой.
    health = brain_provider.load_provider_health(brain).get("items", {})
    seen: set[str] = set()
    for candidates in profiles.values():
        for cand in candidates or []:
            command = brain_provider.candidate_command(matrix, cand)
            executable = command.split()[0] if command else ""
            key = f"{cand.get('provider', '')}/{cand.get('model', '')}"
            if not executable or key in seen:
                continue
            seen.add(key)
            if shutil.which(executable) is None and key not in health:
                issues.append(Issue("WARN", "config/routing.json",
                                    f"{key}: команда {executable!r} не найдена и нет записи о здоровье"))
    return issues


def validate_roles(brain: Path) -> list[Issue]:
    """Роли обязаны иметь машиночитаемый frontmatter.

    Раньше frontmatter был только у teams/*.md, а roles/*.md жили как проза:
    brain-run грепал упоминания doctrine/<slug>.md по тексту, из-за чего
    отрицательное упоминание тоже подгружало доктрину в промпт. Теперь роли —
    это данные (type/doctrine/model_tier/writes), а этот валидатор гарантирует,
    что данные на месте и ссылки на доктрины не битые.
    """
    issues: list[Issue] = []
    role_files = iter_system_files("roles", "*.md", brain=brain)
    if not role_files:
        return issues

    for path in role_files:
        rel = f"roles/{path.name}"
        fm, _body = parse_frontmatter(read_text(path))

        if not fm:
            issues.append(Issue("ERROR", rel,
                                "роль без frontmatter: нужны type: role, "
                                "doctrine, model_tier, writes"))
            continue

        if fm.get("type") != "role":
            issues.append(Issue("ERROR", rel,
                                f"поле type: {fm.get('type')!r}, ожидается 'role'"))

        for field in ("model_tier", "writes"):
            if not str(fm.get(field, "")).strip():
                issues.append(Issue("ERROR", rel,
                                    f"отсутствует поле {field} в frontmatter роли"))

        for slug in as_list(fm.get("doctrine")):
            if not resolve_system_asset(f"doctrine/{slug}.md", brain=brain).is_file():
                issues.append(Issue("ERROR", rel,
                                    f"doctrine: {slug} — нет файла doctrine/{slug}.md"))
    return issues


def validate_escalation_matrix(brain: Path) -> list[Issue]:
    """Машиночитаемая escalation matrix: doctrine/escalation-matrix.yaml.

    Раньше матрица зон (зона → primary → escalate) и налоговые этапы 1–4 жили
    только прозой в MEMORY.md (и её копии в runtime/templates/v2/MEMORY.md):
    не исполнялись, не валидировались и расходились с roles/ бесшумно. Теперь
    файл — единственный источник, а этот валидатор гарантирует, что каждая
    зона ссылается на существующие роли и что файл в принципе на месте.
    """
    from .escalation import load_escalation_matrix

    issues: list[Issue] = []
    rel = "doctrine/escalation-matrix.yaml"
    path = resolve_system_asset(rel, brain=brain)
    has_doctrine = path.parent.is_dir() or (brain / "doctrine").is_dir()
    if not has_doctrine:
        return issues
    if not path.is_file():
        return [Issue("ERROR", rel,
                      "нет файла: escalation matrix должна жить в "
                      "doctrine/escalation-matrix.yaml, а не прозой в MEMORY.md")]

    data, errors = load_escalation_matrix(brain)
    for err in errors:
        issues.append(Issue("ERROR", rel, err))
    if data is None:
        return issues

    if data.get("version") is None:
        issues.append(Issue("ERROR", rel, "отсутствует обязательное поле version"))

    known_roles = {p.stem for p in iter_system_files("roles", "*.md", brain=brain)}

    for section in ("zones", "tax_stages"):
        entries = data.get(section)
        if not isinstance(entries, list):
            issues.append(Issue("ERROR", rel, f"{section}: ожидается список"))
            continue
        seen_ids: set[str] = set()
        for index, entry in enumerate(entries):
            where = f"{section}[{index}]"
            if not isinstance(entry, dict):
                issues.append(Issue("ERROR", rel, f"{where}: ожидается объект зоны"))
                continue
            eid = str(entry.get("id", "")).strip()
            label = f"{section}/{eid or '?'}"
            if not eid:
                issues.append(Issue("ERROR", rel, f"{where}: отсутствует id"))
            if eid and eid in seen_ids:
                issues.append(Issue("ERROR", rel, f"{section}: дубликат id {eid!r}"))
            seen_ids.add(eid)
            if not str(entry.get("name", "")).strip():
                issues.append(Issue("ERROR", rel, f"{label}: отсутствует name"))

            primary = entry.get("primary")
            if not isinstance(primary, list) or not primary:
                issues.append(Issue(
                    "ERROR", rel,
                    f"{label}: primary должен быть непустым списком ролей"))
            else:
                for role in primary:
                    role = str(role).strip()
                    if role and role not in known_roles:
                        issues.append(Issue(
                            "ERROR", rel,
                            f"{label}: primary-роль {role!r} не существует "
                            f"(нет roles/{role}.md)"))

            escalate = entry.get("escalate")
            if escalate is None:
                escalate = []
            if not isinstance(escalate, list):
                issues.append(Issue(
                    "ERROR", rel,
                    f"{label}: escalate должен быть списком ролей"))
            else:
                for role in escalate:
                    role = str(role).strip()
                    if role and role not in known_roles:
                        issues.append(Issue(
                            "ERROR", rel,
                            f"{label}: escalate-роль {role!r} не существует "
                            f"(нет roles/{role}.md)"))
    return issues


def validate_role_uiux_routing(brain: Path) -> list[Issue]:
    issues = []
    has_roles = bool(iter_system_files("roles", "*.md", brain=brain)) \
        or (brain / "roles").is_dir() \
        or resolve_system_asset("roles", brain=brain).is_dir()
    if not has_roles:
        return issues
    has_uiux = bool(iter_system_files("skills/uiux", "**/*.md", brain=brain)) \
        or resolve_system_asset("skills/uiux", brain=brain).is_dir()
    if not has_uiux:
        return issues

    checks = [
        ("designer.md", ["skills/uiux", "[product, designer, developer, reviewer]"]),
        ("product.md", ["[product, designer, developer, reviewer]", "ux-task-framing"]),
        ("developer.md", ["[product, designer, developer, reviewer]", "frontend-handoff-spec"]),
        ("reviewer.md", ["[product, designer, developer, reviewer]", "design-system-guard"]),
        ("copywriter.md", ["microcopy-coordination"]),
        ("linter.md", ["skill pack hygiene"]),
    ]

    for filename, patterns in checks:
        path = resolve_system_asset(f"roles/{filename}", brain=brain)
        rel = f"roles/{filename}"
        if not path.exists():
            issues.append(Issue("WARN", rel, "missing role file for UI/UX routing check"))
            continue
        content = read_text(path)
        for pattern in patterns:
            if pattern not in content:
                issues.append(Issue("ERROR", rel, f"missing UI/UX routing pattern: {pattern}"))

    return issues


# ---------------------------------------------------------------------------
# validate_uiux_skill_pack — split into private helpers
# ---------------------------------------------------------------------------

_REQUIRED_BY_GROUP: dict[str, set[str]] = {
    "core": {
        "ux-task-framing",
        "workflow-design",
        "information-architecture",
        "design-system-guard",
        "accessibility-review",
        "ui-critique",
    },
    "brain": {
        "data-dense-dashboard-design",
        "ai-product-ux",
        "orchestration-ui-patterns",
    },
    "handoff": {
        "frontend-handoff-spec",
        "responsive-behavior-spec",
        "microcopy-coordination",
        "visual-regression-checklist",
        "usability-test-script",
    },
}

_DRAFT_HANDOFF = {"visual-regression-checklist", "usability-test-script"}

_REQUIRED_SECTIONS = [
    "## Trigger",
    "## Inputs",
    "## Checklist",
    "## Output Format",
    "## Forbidden",
    "## See Also",
]

_STATE_MATRIX_ITEMS = ["empty:", "loading:", "error:", "success:", "disabled:"]


def _check_group_dir_exists(uiux_dir: Path, group: str) -> list[Issue]:
    """Check that a group directory exists under skills/uiux/."""
    if not (uiux_dir / group).is_dir():
        return [Issue("ERROR", f"skills/uiux/{group}", "missing UI/UX skill group")]
    return []


def _check_required_skills_present(group_dir: Path, group: str) -> list[Issue]:
    """Check that all required skill files are present in a group directory."""
    present = {path.stem for path in group_dir.glob("*.md")}
    return [
        Issue("ERROR", f"skills/uiux/{group}/{slug}.md", "missing required UI/UX skill")
        for slug in sorted(_REQUIRED_BY_GROUP[group] - present)
    ]


def _check_skill_metadata(rel: str, fm: dict[str, Any], slug: str, group: str, path: Path) -> list[Issue]:
    """Validate frontmatter metadata for a single skill file."""
    issues: list[Issue] = []

    if path.stat().st_size > 8192:
        issues.append(Issue("ERROR", rel, "file size exceeds 8KB"))

    for key in (
        "name", "version", "last_updated", "status", "owner_role", "group",
        "applies_to", "invoked_by", "consumed_by", "trigger", "requires",
        "forbidden_zones", "output_format", "max_lines"
    ):
        if key not in fm:
            issues.append(Issue("ERROR", rel, f"missing frontmatter field {key}"))

    if fm.get("last_updated") and not validate_date(fm["last_updated"]):
        issues.append(Issue("ERROR", rel, f"invalid last_updated date {fm['last_updated']}"))

    if fm.get("name") != slug:
        issues.append(Issue("ERROR", rel, f"name mismatch: {fm.get('name')} != {slug}"))

    status = str(fm.get("status"))
    if status not in ("active", "draft"):
        issues.append(Issue("ERROR", rel, f"invalid status: {status}"))

    if fm.get("group") != group:
        issues.append(Issue("ERROR", rel, f"group mismatch: {fm.get('group')} != {group}"))

    applies_to = as_list(fm.get("applies_to"))
    if "designer" not in applies_to:
        issues.append(Issue("ERROR", rel, "must apply to designer"))

    try:
        max_lines = int(fm.get("max_lines", 0))
        if max_lines > 200:
            issues.append(Issue("ERROR", rel, f"max_lines {max_lines} exceeds 200"))
    except (ValueError, TypeError):
        issues.append(Issue("ERROR", rel, "invalid max_lines"))

    return issues


def _check_skill_sections(rel: str, content: str) -> list[Issue]:
    """Check that all required markdown sections are present in a skill file."""
    return [
        Issue("ERROR", rel, f"missing required section: {section}")
        for section in _REQUIRED_SECTIONS
        if section not in content
    ]


def _check_state_matrix(rel: str, content: str, group: str) -> list[Issue]:
    """Check state matrix items for core and brain skills."""
    if group not in ("core", "brain"):
        return []
    return [
        Issue("ERROR", rel, f"missing state matrix item: {item}")
        for item in _STATE_MATRIX_ITEMS
        if item not in content
    ]


def _check_skill_status(rel: str, slug: str, group: str, status: str) -> list[Issue]:
    """Validate status is correct for the group (active vs draft)."""
    issues: list[Issue] = []
    if group in ("core", "brain") and slug in _REQUIRED_BY_GROUP[group] and status != "active":
        issues.append(Issue("ERROR", rel, f"{group} skill {slug} must be active"))
    if group == "handoff" and slug in _REQUIRED_BY_GROUP[group]:
        expected = "draft" if slug in _DRAFT_HANDOFF else "active"
        if status != expected:
            issues.append(Issue("ERROR", rel, f"handoff skill {slug} must be {expected}"))
    return issues


def validate_uiux_skill_pack(brain: Path) -> list[Issue]:
    """Validate the full skills/uiux/ skill pack structure and contents."""
    issues: list[Issue] = []
    pack_files = iter_system_files("skills/uiux", "**/*.md", brain=brain)
    if not pack_files and not resolve_system_asset("skills/uiux", brain=brain).is_dir():
        return issues

    files_by_group: dict[str, list[Path]] = {"core": [], "brain": [], "handoff": []}
    for path in pack_files:
        group = path.parent.name
        if group in files_by_group:
            files_by_group[group].append(path)

    for group in ("core", "brain", "handoff"):
        if not files_by_group[group] and not resolve_system_asset(f"skills/uiux/{group}", brain=brain).is_dir():
            issues.extend(_check_group_dir_exists(
                resolve_system_asset("skills/uiux", brain=brain), group))
            continue

        present = {p.stem for p in files_by_group[group]}
        for slug in _REQUIRED_BY_GROUP[group]:
            if slug not in present:
                issues.append(Issue("ERROR", f"skills/uiux/{group}/{slug}.md",
                                    "missing required UI/UX skill"))

        for path in files_by_group[group]:
            rel = system_asset_rel(path, brain=brain)
            slug = path.stem
            content = read_text(path)
            fm, _body = parse_frontmatter(content)

            if not fm:
                issues.append(Issue("ERROR", rel, "missing frontmatter"))
                continue

            issues.extend(_check_skill_metadata(rel, fm, slug, group, path))
            issues.extend(_check_skill_sections(rel, content))
            issues.extend(_check_state_matrix(rel, content, group))
            status = str(fm.get("status"))
            issues.extend(_check_skill_status(rel, slug, group, status))

    return issues


def get_uiux_skill_slugs(brain: Path) -> set[str]:
    slugs: set[str] = set()
    for path in iter_system_files("skills/uiux", "**/*.md", brain=brain):
        slugs.add(path.stem)
    return slugs


def validate_uiux_stale_references(brain: Path) -> list[Issue]:
    issues: list[Issue] = []
    slugs = get_uiux_skill_slugs(brain)
    if not slugs:
        return issues

    group_slugs: dict[str, set[str]] = {"core": set(), "brain": set(), "handoff": set()}
    for path in iter_system_files("skills/uiux", "**/*.md", brain=brain):
        group = path.parent.name
        if group in group_slugs:
            group_slugs[group].add(path.stem)

    search_dirs = ["roles", "spec", "handoff"]
    skill_prefixes = (
        "ux-", "ui-", "design-system-", "frontend-", "responsive-",
        "microcopy-", "visual-regression-", "usability-test-", "data-dense-",
        "ai-product-", "orchestration-", "workflow-", "information-",
        "accessibility-"
    )

    for dir_name in search_dirs:
        if dir_name == "roles":
            paths = iter_system_files("roles", "*.md", brain=brain)
        else:
            d = brain / dir_name
            paths = list(d.glob("**/*.md")) if d.is_dir() else []
        for path in paths:
            rel = system_asset_rel(path, brain=brain)
            content = read_text(path)

            for match in re.finditer(r"skills/uiux/([a-z0-9/-]+)", content):
                ref = match.group(1).rstrip("/")
                if ref in ("core", "brain", "handoff"):
                    continue
                if "/" in ref:
                    parts = ref.split("/")
                    if len(parts) == 2:
                        group, slug = parts
                        if group not in group_slugs or slug not in group_slugs[group]:
                            issues.append(Issue("ERROR", rel, f"broken skill reference: skills/uiux/{ref}"))
                    else:
                        issues.append(Issue("ERROR", rel, f"invalid skill path format: skills/uiux/{ref}"))
                else:
                    if ref not in slugs:
                        issues.append(Issue("ERROR", rel, f"broken skill reference: skills/uiux/{ref}"))

            for match in re.finditer(r"`([a-z0-9-]+)`", content):
                word = match.group(1)
                if any(word.startswith(p) for p in skill_prefixes):
                    if word not in slugs:
                        issues.append(Issue("ERROR", rel, f"broken skill reference: `{word}`"))

    return issues


def validate_all(brain_value: "str | Path | None" = None) -> list[Issue]:
    from .pages import brain_path
    brain = brain_path(str(brain_value) if brain_value else None)
    issues = validate_paths(brain)
    issues.extend(validate_staged_write_path(brain))
    if any(issue.severity == "ERROR" for issue in issues):
        return issues

    issues.extend(validate_system_paths_not_restored(brain))
    slugs = all_page_slugs(brain)
    for raw in sorted((brain / "raw").glob("*.md")):
        issues.extend(validate_raw_source(brain, raw))
    for page in iter_wiki_pages(brain):
        issues.extend(validate_wiki_page(brain, page, slugs))
    issues.extend(validate_index(brain, slugs))
    issues.extend(validate_task_refs(brain, brain / "tasks" / "active.md", slugs))
    issues.extend(validate_task_refs(brain, brain / "tasks" / "done.md", slugs))
    issues.extend(validate_task_client_fields(brain, brain / "tasks" / "active.md"))
    issues.extend(validate_task_client_fields(brain, brain / "tasks" / "done.md"))
    # Только по активной очереди: done.md — архив, он хранит запись о том, что
    # было сделано и какой моделью. Переписывать его задним числом значило бы
    # подделать журнал.
    issues.extend(validate_queue_scope(brain, brain / "tasks" / "active.md"))
    issues.extend(validate_routing(brain))
    issues.extend(validate_roles(brain))
    issues.extend(validate_escalation_matrix(brain))
    issues.extend(validate_role_uiux_routing(brain))
    issues.extend(validate_uiux_skill_pack(brain))
    issues.extend(validate_uiux_stale_references(brain))
    return issues
