import os, sys, re, json
from pathlib import Path

def check_missing_skills_and_spawn(task_id: str):
    brain_path = Path(os.environ.get("BRAIN_PATH", os.path.expanduser("~/brain")))
    active_path = brain_path / "tasks" / "active.md"
    if not active_path.exists():
        return
    active_md = active_path.read_text(errors="ignore")
    
    in_block = False
    lines = []
    for line in active_md.split("\n"):
        if re.match(r"^- \[[~x \!]\]", line):
            if task_id in line:
                in_block = True
                lines.append(line)
            else:
                if in_block:
                    break
        elif in_block:
            if line.startswith("##"):
                break
            lines.append(line)
            
    if not lines:
        return
        
    task_text = "\n".join(lines)
    
    req_match = re.search(r"^\s*requires:\s*(.+)$", task_text, re.MULTILINE)
    if not req_match:
        return
        
    reqs = [s.strip() for s in req_match.group(1).strip("[]").split(",") if s.strip()]
    
    skills_dir = brain_path / "skills"
    existing_skills = set()
    if skills_dir.exists():
        try:
            from brain_skill_parser import parse_skill_file
            for md in skills_dir.rglob("*.md"):
                data = parse_skill_file(md)
                if data and "name" in data:
                    existing_skills.add(data["name"])
        except Exception as e:
            pass
                
    missing = [req for req in reqs if req not in existing_skills]
    
    if not missing:
        return
        
    health_file = brain_path / ".provider-health.json"
    if health_file.exists():
        try:
            health = json.loads(health_file.read_text())
            clients = health.get("clients", {})
            statuses = [str(v.get("status", "OK")).upper() for v in clients.values() if isinstance(v, dict)]
            if statuses and all(s == "CRITICAL" for s in statuses):
                print(f"Skill(s) {missing} missing, but all clients are CRITICAL. Not spawning.", file=sys.stderr)
                return
        except Exception:
            pass
            
    import subprocess
    
    # === Option B: Systemic Wishlist Integration ===
    wishlist_path = brain_path / "wiki" / "wishlist.json"
    wishlist = []
    if wishlist_path.exists():
        try:
            wishlist = json.loads(wishlist_path.read_text())
        except Exception:
            pass

    # Add missing skills to wishlist
    modified_wishlist = False
    for skill in missing:
        # Check if already in wishlist
        if not any(w.get("trigger") == skill and w.get("type") == "missing_skill" for w in wishlist):
            wishlist.append({
                "type": "missing_skill",
                "trigger": skill,
                "count": 1,
                "status": "pending_search"
            })
            modified_wishlist = True

    if modified_wishlist:
        wishlist_path.parent.mkdir(parents=True, exist_ok=True)
        wishlist_path.write_text(json.dumps(wishlist, indent=2))

    # Run curator pipeline
    subprocess.run(["brain-curator", "search"], stdout=sys.stderr)
    subprocess.run(["brain-curator", "synthesize"], stdout=sys.stderr)

    # Reload wishlist to check for proposals
    wishlist = []
    if wishlist_path.exists():
        try:
            wishlist = json.loads(wishlist_path.read_text())
        except Exception:
            pass

    for skill in missing:
        # Find the skill in the wishlist
        w_item = next((w for w in wishlist if w.get("trigger") == skill and w.get("type") == "missing_skill"), None)

        if w_item and w_item.get("status") == "proposed" and w_item.get("proposal_path"):
            title = f"Review curator proposal for missing skill: {skill}"
            subprocess.run(["brain-task", "add", title, "--role", "reviewer", "--prio", "P0"], stdout=sys.stderr)
        else:
            title = f"Generate skill {skill} for the active CLI"
            subprocess.run(["brain-task", "add", title, "--role", "developer", "--prio", "P0"], stdout=sys.stderr)
        
    subprocess.run(["brain-task", "block", task_id, f"missing skills: {', '.join(missing)}"], stdout=sys.stderr)
    print("BLOCKED", end="")
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_missing_skills_and_spawn(sys.argv[1])
