import os
import re
from pathlib import Path
from typing import Dict, Any, List

def parse_skill_file(filepath: Path) -> Dict[str, Any]:
    """Parse a single skill file's YAML frontmatter."""
    try:
        from brain_wiki.frontmatter import parse_frontmatter
    except ImportError:
        # Fallback if brain_wiki is somehow missing
        return {}
        
    try:
        content = filepath.read_text(encoding="utf-8")
        data, body = parse_frontmatter(content)
        if not data:
            return {}
        data["_content"] = body.strip()
        data["_filepath"] = str(filepath)
        return data
    except Exception:
        return {}

def validate_skill(data: Dict[str, Any]) -> bool:
    """Validate that a skill has required fields."""
    required = ["name", "type", "applies_to", "supported_clients"]
    if not all(k in data for k in required):
        return False
    if not isinstance(data["applies_to"], list):
        return False
    if not isinstance(data["supported_clients"], list):
        return False
    if data["type"] == "mcp" and "mcp_command" not in data:
        return False
    return True

def _skill_files(skills_dir: Path | None) -> List[Path]:
    """Файлы скиллов: явный каталог, либо merge $BRAIN + $BRAIN_SYSTEM_PATH."""
    from brain_core.paths import brain_path, iter_system_files

    if skills_dir is None:
        return iter_system_files("skills", "**/*.md")
    try:
        same = skills_dir.resolve() == (brain_path() / "skills").resolve()
    except OSError:
        same = False
    if same:
        return iter_system_files("skills", "**/*.md")
    if not skills_dir.exists():
        return []
    return [p for p in skills_dir.rglob("*.md") if p.is_file()]


def get_skills_for_role(role: str, client: str, skills_dir: Path | None) -> List[Dict[str, Any]]:
    """Get validated skills applicable to a specific role and client."""
    skills = []
    for filepath in _skill_files(skills_dir):
        data = parse_skill_file(filepath)
        if not data or not validate_skill(data):
            continue

        applies = data.get("applies_to", [])
        clients = data.get("supported_clients", [])

        if role in applies and (client in clients or "all" in clients):
            skills.append(data)
            
    return skills

def get_pinned_client_for_role(role: str, skills_dir: Path | None) -> str | None:
    """Check if any skill for this role requires a specific client (platform pinning)."""
    for filepath in _skill_files(skills_dir):
        data = parse_skill_file(filepath)
        if not data or not validate_skill(data):
            continue

        applies = data.get("applies_to", [])
        clients = data.get("supported_clients", [])

        if role in applies:
            if "all" not in clients and len(clients) > 0:
                # This skill restricts to a limited set of clients. Pin to the first one.
                return clients[0]
                
    return None

def _parse_task_requires(active_md_path: Path, task_id: str) -> List[str]:
    """Extract `requires` list for a specific task from tasks/active.md."""
    if not active_md_path.exists():
        return []
    text = active_md_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    in_block = False
    block: list[str] = []
    for line in lines:
        if re.match(r"^- \[[~x !]\]", line):
            if task_id in line:
                in_block = True
                block.append(line)
                continue
            if in_block:
                break
        elif in_block:
            if line.startswith("##"):
                break
            block.append(line)
    if not block:
        return []
    m = re.search(r"^\s*requires:\s*(.+)$", "\n".join(block), re.MULTILINE)
    if not m:
        return []
    raw = m.group(1).strip().strip("[]")
    return [s.strip() for s in raw.split(",") if s.strip()]

def get_pinned_client_for_task_role(role: str, task_id: str, brain_path: Path) -> str | None:
    """Клиент, закреплённый за задачей скиллом, который она требует.

    Закрепление действует только на задачи с `requires:`. Раньше при пустом
    `requires:` был откат на закрепление по роли — и тогда один скилл с
    ограниченным supported_clients пришпиливал ВСЕ задачи роли к своему
    клиенту. Так skills/playwright (applies_to: developer, qa) молча уводил
    каждую задачу разработчика на claude, и запись `developer → opencode` в
    конфигурации маршрутизации не срабатывала никогда: закрепление стоит в
    приоритете выше конфигурации, поэтому безусловный откат делал саму
    конфигурацию недостижимой.

    Вопрос «какие клиенты вообще умеют скиллы этой роли» отвечает
    get_pinned_client_for_role — но это не основание переопределять маршрут.
    """
    required = set(_parse_task_requires(brain_path / "tasks" / "active.md", task_id))
    if not required:
        return None
    for filepath in _skill_files(brain_path / "skills"):
        data = parse_skill_file(filepath)
        if not data or not validate_skill(data):
            continue
        if data.get("name") not in required:
            continue
        applies = data.get("applies_to", [])
        clients = data.get("supported_clients", [])
        if role in applies and "all" not in clients and len(clients) > 0:
            return clients[0]
    return None
