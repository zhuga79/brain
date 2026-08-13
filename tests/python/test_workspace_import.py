import pytest
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent.parent
SRC_LIB = REPO / "runtime" / "lib"
sys.path.insert(0, str(SRC_LIB))
if "brain_workspace" in sys.modules:
    loaded_from = Path(getattr(sys.modules["brain_workspace"], "__file__", "")).resolve()
    if not loaded_from.is_relative_to(SRC_LIB):
        del sys.modules["brain_workspace"]

from brain_workspace import parse_project_descriptor

def test_parse_project_descriptor_json():
    content = """
    {
        "name": "Test Project",
        "goal": "Build something",
        "tasks": ["t-1", "t-2"],
        "roles": ["developer", "architect"]
    }
    """
    res = parse_project_descriptor(content)
    assert res["name"] == "Test Project"
    assert res["goal"] == "Build something"
    assert res["tasks"] == ["t-1", "t-2"]
    assert res["roles"] == ["developer", "architect"]

def test_parse_project_descriptor_markdown():
    content = """
# Markdown Project

## Goal
This is a goal
with multiple lines.

## Tasks
- task 1
* task 2

## Roles
- developer
- pm
"""
    res = parse_project_descriptor(content)
    assert res["name"] == "Markdown Project"
    assert res["goal"] == "This is a goal\nwith multiple lines."
    assert res["tasks"] == ["task 1", "task 2"]
    assert res["roles"] == ["developer", "pm"]

def test_parse_project_descriptor_invalid():
    content = "just some random text"
    with pytest.raises(ValueError, match="Descriptor must have at least a name or a goal"):
        parse_project_descriptor(content)
