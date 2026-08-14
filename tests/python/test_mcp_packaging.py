import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "runtime" / "mcp"))

import packaging  # type: ignore


def _write_fake_mcp(site_dir: Path) -> None:
    pkg_dir = site_dir / "mcp" / "server"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "mcp" / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "fastmcp.py").write_text(
        """
class FastMCP:
    def __init__(self, name):
        self.name = name
        self._tools = []

    def tool(self):
        def decorator(func):
            self._tools.append(func)
            return func
        return decorator

    def resource(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def run(self, *args, **kwargs):
        return None
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_install_tree_removes_stale_files_and_writes_matching_manifest(tmp_path):
    install_root = tmp_path / "brain-mcp"
    install_root.mkdir()
    (install_root / "server.py").write_text("legacy\n", encoding="utf-8")
    stale = install_root / "runtime" / "mcp" / "stale.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale\n", encoding="utf-8")

    manifest = packaging.install_tree(PROJECT_ROOT, install_root)

    assert manifest["status"] == "ok"
    assert not (install_root / "server.py").exists()
    assert not stale.exists()

    verify = packaging.verify_install(PROJECT_ROOT, install_root)
    assert verify["status"] == "ok"
    assert verify["missing"] == []
    assert verify["mismatches"] == []
    assert verify["extras"] == []

    manifest_path = install_root / "manifest.json"
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["files"] == manifest["files"]


def test_verify_install_reports_mismatch_and_extra_file(tmp_path):
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(PROJECT_ROOT, install_root)

    target = install_root / "runtime" / "mcp" / "server.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    extra = install_root / "runtime" / "mcp" / "old-monolith.py"
    extra.write_text("print('old')\n", encoding="utf-8")

    verify = packaging.verify_install(PROJECT_ROOT, install_root)
    mismatch_names = {item["path"] for item in verify["mismatches"]}
    extra_names = {item["path"] for item in verify["extras"]}

    assert verify["status"] == "drift"
    assert "runtime/mcp/server.py" in mismatch_names
    assert "runtime/mcp/old-monolith.py" in extra_names


def test_installed_tree_supports_server_import_and_help(tmp_path):
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(PROJECT_ROOT, install_root)

    fake_site = tmp_path / "fake-site"
    _write_fake_mcp(fake_site)

    pythonpath = os.pathsep.join(
        [
            str(fake_site),
            str(install_root / "runtime" / "lib"),
            str(install_root / "runtime" / "mcp"),
        ]
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath
    env["BRAIN_PATH"] = str(tmp_path / "brain")
    (tmp_path / "brain").mkdir()

    import_cmd = [
        sys.executable,
        "-c",
        "import server; print(server.BRAIN)",
    ]
    import_result = subprocess.run(import_cmd, capture_output=True, text=True, env=env, check=False)
    assert import_result.returncode == 0, import_result.stderr

    help_cmd = [sys.executable, str(install_root / "runtime" / "mcp" / "server.py"), "--help"]
    help_result = subprocess.run(help_cmd, capture_output=True, text=True, env=env, check=False)
    assert help_result.returncode == 0, help_result.stderr
    assert "Brain MCP server" in help_result.stdout


def test_brain_status_reports_missing_optional_mcp_parity(tmp_path):
    brain = tmp_path / "brain"
    for rel in ("wiki", "tasks", "council", "raw"):
        (brain / rel).mkdir(parents=True, exist_ok=True)
    (brain / "tasks" / "active.md").write_text("# Active\n", encoding="utf-8")
    (brain / "tasks" / "done.md").write_text("# Done\n", encoding="utf-8")
    (brain / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (brain / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["BRAIN_PATH"] = str(brain)
    env["BRAIN_SYSTEM_PATH"] = str(PROJECT_ROOT)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "runtime" / "lib")

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "runtime" / "bin" / "brain-status"), "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    parity = payload["mcp_parity"]
    assert parity["status"] == "missing"
    assert parity["drift_count"] == 0
    assert "install-brain-mcp.sh" in parity["remediation"]
