import pytest
from pathlib import Path
from brain_skill_parser import parse_skill_file, validate_skill, get_skills_for_role

def test_parse_skill_file_missing_frontmatter(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("body only")
    res = parse_skill_file(f)
    assert res == {}

def test_parse_skill_file_unclosed_frontmatter(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("---\nname: test\nbody only")
    res = parse_skill_file(f)
    assert res == {}

def test_parse_skill_file_invalid_yaml(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("---\nname: test\n  bad: indent\n---\nbody")
    res = parse_skill_file(f)
    # Simple parser strips and accepts this
    assert res["name"] == "test"
    assert res["bad"] == "indent"

def test_parse_skill_file_non_dict_yaml(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("---\n- just_a_list\n---\nbody")
    res = parse_skill_file(f)
    assert res == {}

def test_parse_skill_file(tmp_path):
    f = tmp_path / "skill.md"
    f.write_text("---\nname: test\n---\nbody")
    res = parse_skill_file(f)
    assert res["name"] == "test"
    assert res["_content"] == "body"

def test_validate_skill_mcp():
    valid = {"name": "p", "type": "mcp", "applies_to": ["qa"], "supported_clients": ["claude"], "mcp_command": "npx"}
    assert validate_skill(valid)
    
    invalid = {"name": "p", "type": "mcp", "applies_to": ["qa"], "supported_clients": ["claude"]}
    assert not validate_skill(invalid)

def test_validate_skill_invalid_types():
    assert not validate_skill({"name": "p", "type": "mcp", "applies_to": "qa", "supported_clients": ["claude"]})
    assert not validate_skill({"name": "p", "type": "mcp", "applies_to": ["qa"], "supported_clients": "claude"})

def test_get_skills_for_role(tmp_path):
    skills_dir = tmp_path / "skills"
    
    # test non-existent dir
    assert get_skills_for_role("qa", "claude", skills_dir) == []
    
    skills_dir.mkdir()
    
    (skills_dir / "valid_mcp.md").write_text("---\nname: p\ntype: mcp\napplies_to: [qa]\nsupported_clients: [claude]\nmcp_command: npx\n---\nbody")
    (skills_dir / "valid_know.md").write_text("---\nname: k\ntype: knowledge\napplies_to: [qa, dev]\nsupported_clients: [all]\n---\nbody")
    (skills_dir / "SKILL.md").write_text("---\nname: s\ntype: knowledge\napplies_to: [qa]\nsupported_clients: [all]\n---\nbody")
    (skills_dir / "invalid.md").write_text("---\nname: x\n---\nbody")
    
    qa_claude = get_skills_for_role("qa", "claude", skills_dir)
    assert len(qa_claude) == 3
    
    qa_ollama = get_skills_for_role("qa", "ollama", skills_dir)
    assert len(qa_ollama) == 2
    
    dev_claude = get_skills_for_role("dev", "claude", skills_dir)
    assert len(dev_claude) == 1
    assert dev_claude[0]["name"] == "k"
