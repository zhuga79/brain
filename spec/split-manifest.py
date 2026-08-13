#!/usr/bin/env python3
"""Классификатор путей для spec/split-manifest.md.

Воспроизводит разбор на системный код и слой данных: печатает счётчики
и кросс-корневые wikilink'и.
Используется задачами t-2026-08-10-split-history и t-2026-08-10-wiki-split.
"""
import re
import subprocess
from pathlib import Path

BRAIN = Path.home() / "brain"

# config/ публичен: routing.json — системная настройка маршрутизации, без
# секретов. Пришёл на смену .cli-mapping.sh и wiki/provider-matrix.json,
# которых в дереве больше нет — записи о них из манифеста сняты.
PUBLIC_DIRS = (".github/", "config/", "docs/", "doctrine/", "roles/", "runtime/",
               "skills/", "spec/", "teams/", "tests/")

PUBLIC_ROOT = {
    "README.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE", "MEMORY.md",
    "AGENTS.md", "GEMINI.md", "brain-spec.md", "pyproject.toml", ".gitignore",
    "setup-brain-v2.sh", "install-brain-mcp.sh",
    "install-hooks.sh", "install-obsidian-skills.sh", "add-teams-brain.sh",
    "add-power-features-brain.sh", "add-pm-finance-brain.sh",
    "add-design-negotiator-brain.sh", "patch-brain-run-doctrine.sh",
    "refine-tax-boundaries.sh",
}

PUBLIC_EXACT = {
    "tasks/SCHEMA.md",
    "prd/_TEMPLATE.md",
    "raw/smoke-e2e-2026-05-03.md",
}

# wiki-страницы, которые переезжают в docs/ публичного репозитория
WIKI_PUBLIC = {
    "about-brain", "architecture-overview", "cli-agents", "cli-cheatsheet",
    "council-guardrails", "federation-sync", "learning-loop", "roles-overview",
    "security-handoffs", "skill-curator", "uiux-reference", "vector-search",
    "workflow-solo-council", "model-fleet-report",
    "source-smoke-e2e-2026-05-03", "phase-13-prd",
    "prd-t-2026-05-09-code-review-brain-runtime",
}
WIKI_DECISIONS = {
    "decision-interactive-surface", "decision-llm-stack",
    "decision-public-source-of-truth", "decision-role-model-routing",
    "decision-runtime-core-boundaries", "decisions-log",
}

# контракты из handoff/, которые едут в spec/ после снятия абсолютных путей
HANDOFF_PUBLIC = {
    "handoff/brain-federation-contract.md",
    "handoff/federation-git-sync-contract.md",
    "handoff/phase8-api-contract.md",
    "handoff/provider-health-refresh-contract.md",
    "handoff/token-economy-contract.md",
    "handoff/OPS_RUNBOOK.md",
}


# исключения внутри публичных каталогов
PRIVATE_EXACT = {
    # команда собрана под конкретное дело: описания ролей насыщены его предметом
    "teams/insurance-fraud.md",
}


def classify(rel: str) -> str:
    if rel in PRIVATE_EXACT:
        return "private"
    if rel.startswith(PUBLIC_DIRS):
        return "public"
    if rel in PUBLIC_ROOT or rel in PUBLIC_EXACT or rel in HANDOFF_PUBLIC:
        return "public"
    if rel.startswith("wiki/") and rel.endswith(".md") and "/" not in rel[5:]:
        stem = rel[5:-3]
        if stem in WIKI_PUBLIC or stem in WIKI_DECISIONS:
            return "public"
    return "private"


tracked = subprocess.run(["git", "ls-files"], cwd=BRAIN, capture_output=True,
                         text=True, check=True).stdout.split()

cls = {rel: classify(rel) for rel in tracked}

pub = sorted(r for r, c in cls.items() if c == "public")
priv = sorted(r for r, c in cls.items() if c == "private")
print(f"tracked={len(tracked)} public={len(pub)} private={len(priv)}")

# --- что публикуется сегодня ---
today = set()
public_dir = Path("/home/user/Документы/Brain/brain-public")
for p in public_dir.rglob("*"):
    if p.is_file() and ".git/" not in str(p):
        today.add(str(p.relative_to(public_dir)))

pubset = set(pub)
print("\n--- сегодня публикуется, манифест делает приватным ---")
for r in sorted(today - pubset):
    print("  ", r)
print("\n--- манифест делает публичным, сегодня не публикуется ---")
for r in sorted(pubset - today):
    print("  ", r)

# --- кросс-корневые wikilink'и ---
link_re = re.compile(r"\[\[([^\]|#]+)")
stems = {}
for rel in tracked:
    if rel.endswith(".md"):
        stems[Path(rel).stem] = cls[rel]

cross = []
for rel in tracked:
    if not rel.endswith(".md"):
        continue
    text = (BRAIN / rel).read_text(encoding="utf-8", errors="replace")
    for name in link_re.findall(text):
        name = name.strip()
        target = stems.get(name)
        if target and target != cls[rel]:
            cross.append((cls[rel], rel, target, name))

print(f"\n--- кросс-корневые wikilink'и: {len(cross)} ---")
seen = set()
for src_c, src, dst_c, dst in sorted(cross):
    key = (src, dst)
    if key in seen:
        continue
    seen.add(key)
    print(f"  {src_c:7} {src}  ->  {dst_c:7} [[{dst}]]")
