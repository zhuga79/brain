import json
import os
import stat
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "runtime" / "mcp"))

import packaging  # type: ignore


def _tree_snapshot(root: Path) -> dict[str, str]:
    """Содержимое установленного дерева: путь → sha256, без служебных записей."""
    return {rel: packaging._sha256(root / rel) for rel in packaging._installed_files(root)}


def _internal_leftovers(root: Path) -> list[str]:
    return sorted(entry.name for entry in root.iterdir() if packaging._is_internal(entry.name))


def _installed_manifest(root: Path) -> dict:
    """Манифест установки. verify его игнорирует, поэтому проверяем отдельно."""
    return json.loads((root / packaging.MANIFEST_NAME).read_text(encoding="utf-8"))


def _fake_system_root(tmp_path: Path, marker: str = "one") -> Path:
    """Маленькое исходное дерево: сбои удобнее вносить по счётчику файлов."""
    system = tmp_path / f"system-{marker}"
    mcp = system / "runtime" / "mcp"
    lib = system / "runtime" / "lib" / "brain_core"
    mcp.mkdir(parents=True)
    lib.mkdir(parents=True)
    (mcp / "server.py").write_text(f"# server {marker}\n", encoding="utf-8")
    (mcp / "common.py").write_text(f"# common {marker}\n", encoding="utf-8")
    (mcp / "tools_tasks.py").write_text(f"# tools {marker}\n", encoding="utf-8")
    (lib / "__init__.py").write_text("", encoding="utf-8")
    (lib / "paths.py").write_text(f"# paths {marker}\n", encoding="utf-8")
    executable = mcp / "entry.py"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    executable.chmod(0o755)
    return system


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


def _run_brain_status_mcp_parity(tmp_path: Path, install_root: Path, launcher: Path) -> dict:
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
    env["BRAIN_MCP_DIR"] = str(install_root)
    env["BRAIN_MCP_LAUNCHER"] = str(launcher)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "runtime" / "lib")

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "runtime" / "bin" / "brain-status"), "--json"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["mcp_parity"]


def test_brain_status_matched_counts_manifest_files_not_launcher(tmp_path):
    """A missing launcher is its own diagnostic (launcher_present + drift_count).
    It must not make the runtime tree read one manifest file short."""
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(PROJECT_ROOT, install_root)
    file_count = packaging.source_manifest(PROJECT_ROOT)["file_count"]

    launcher = tmp_path / "bin" / "brain-mcp"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    clean = _run_brain_status_mcp_parity(tmp_path, install_root, launcher)
    assert clean["status"] == "ok"
    assert clean["launcher_present"] is True
    assert clean["matched"] == file_count
    assert clean["drift_count"] == 0

    launcher.unlink()
    no_launcher = _run_brain_status_mcp_parity(tmp_path, install_root, launcher)
    assert no_launcher["status"] == "drift"
    assert no_launcher["launcher_present"] is False
    # tree is intact — matched still covers every manifest file
    assert no_launcher["matched"] == file_count
    # the only drift is the launcher
    assert no_launcher["drift_count"] == 1
    assert {item["path"] for item in no_launcher["missing"]} == {"launcher"}


# ---------------------------------------------------------------------------
# t-2026-08-14-mcp-package-atomic-refresh-sta:
# install больше не сносит установленное дерево до копирования нового.
# Ниже — сбои на каждом этапе (copy / verify / swap) и проверка того, что
# предыдущая установка либо цела, либо восстанавливается детерминированно.
# ---------------------------------------------------------------------------


def test_successful_install_leaves_no_temp_or_backup(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"

    first = packaging.install_tree(system, install_root)
    second = packaging.install_tree(system, install_root)

    assert first["status"] == "ok"
    assert first["recovered"] is False
    assert second["recovered"] is False
    assert packaging.verify_install(system, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_failed_copy_leaves_previous_install_untouched(tmp_path, monkeypatch):
    system_old = _fake_system_root(tmp_path, "old")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system_old, install_root)
    before = _tree_snapshot(install_root)

    system_new = _fake_system_root(tmp_path, "new")
    real_copy = packaging._copy_file
    seen = {"count": 0}

    def flaky_copy(source, target):
        seen["count"] += 1
        if seen["count"] == 3:
            raise OSError("no space left on device")
        real_copy(source, target)

    monkeypatch.setattr(packaging, "_copy_file", flaky_copy)

    with pytest.raises(OSError):
        packaging.install_tree(system_new, install_root)

    assert _tree_snapshot(install_root) == before
    assert packaging.verify_install(system_old, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_staged_tree_failing_its_manifest_never_reaches_install_root(tmp_path, monkeypatch):
    system_old = _fake_system_root(tmp_path, "old")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system_old, install_root)
    before = _tree_snapshot(install_root)

    system_new = _fake_system_root(tmp_path, "new")
    real_copy = packaging._copy_file

    def truncating_copy(source, target):
        real_copy(source, target)
        if target.name == "paths.py":
            target.write_text("# corrupted in flight\n", encoding="utf-8")

    monkeypatch.setattr(packaging, "_copy_file", truncating_copy)

    with pytest.raises(packaging.InstallError):
        packaging.install_tree(system_new, install_root)

    assert _tree_snapshot(install_root) == before
    assert packaging.verify_install(system_old, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_interrupt_during_swap_rolls_back_to_previous_install(tmp_path, monkeypatch, fail_at):
    system_old = _fake_system_root(tmp_path, "old")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system_old, install_root)
    legacy = install_root / "legacy-server.py"
    legacy.write_text("legacy\n", encoding="utf-8")
    before = _tree_snapshot(install_root)
    manifest_before = _installed_manifest(install_root)

    system_new = _fake_system_root(tmp_path, "new")
    real_rename = packaging._rename
    seen = {"count": 0}

    def interrupted_rename(source, target):
        seen["count"] += 1
        if seen["count"] == fail_at:
            raise KeyboardInterrupt()
        real_rename(source, target)

    monkeypatch.setattr(packaging, "_rename", interrupted_rename)

    with pytest.raises(KeyboardInterrupt):
        packaging.install_tree(system_new, install_root)

    assert seen["count"] >= fail_at
    assert _tree_snapshot(install_root) == before
    assert _installed_manifest(install_root) == manifest_before
    assert legacy.read_text(encoding="utf-8") == "legacy\n"
    assert packaging.verify_install(system_old, install_root)["missing"] == []
    assert packaging.verify_install(system_old, install_root)["mismatches"] == []
    assert _internal_leftovers(install_root) == []


@pytest.mark.parametrize("fail_at", [2, 3, 4])
def test_killed_swap_is_recovered_deterministically(tmp_path, fail_at):
    """Жёсткий обрыв: процесс уходит через os._exit посреди подмены.

    Ни finally, ни обработчики не отрабатывают — ровно как при kill -9 или
    отключении питания. Дерево обязано восстанавливаться по журналу.
    """
    system_old = _fake_system_root(tmp_path, "old")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system_old, install_root)
    before = _tree_snapshot(install_root)
    manifest_before = _installed_manifest(install_root)

    system_new = _fake_system_root(tmp_path, "new")
    script = textwrap.dedent(
        f"""
        import os
        import sys

        sys.path.insert(0, {str(PROJECT_ROOT / "runtime" / "mcp")!r})
        import packaging

        real_rename = packaging._rename
        seen = {{"count": 0}}

        def crashing_rename(source, target):
            seen["count"] += 1
            if seen["count"] == {fail_at}:
                os._exit(9)
            real_rename(source, target)

        packaging._rename = crashing_rename
        packaging.install_tree({str(system_new)!r}, {str(install_root)!r})
        """
    )
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert crashed.returncode == 9, crashed.stderr

    assert (install_root / packaging.JOURNAL_NAME).is_file()

    report = packaging.recover_install(install_root)

    assert report["recovered"] is True
    assert _tree_snapshot(install_root) == before
    assert _installed_manifest(install_root) == manifest_before
    assert packaging.verify_install(system_old, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_install_after_killed_swap_recovers_then_installs(tmp_path):
    system_old = _fake_system_root(tmp_path, "old")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system_old, install_root)

    system_new = _fake_system_root(tmp_path, "new")
    script = textwrap.dedent(
        f"""
        import os
        import sys

        sys.path.insert(0, {str(PROJECT_ROOT / "runtime" / "mcp")!r})
        import packaging

        real_rename = packaging._rename

        def crashing_rename(source, target):
            real_rename(source, target)
            os._exit(9)

        packaging._rename = crashing_rename
        packaging.install_tree({str(system_new)!r}, {str(install_root)!r})
        """
    )
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert crashed.returncode == 9, crashed.stderr

    result = packaging.install_tree(system_new, install_root)

    assert result["recovered"] is True
    assert packaging.verify_install(system_new, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_install_preserves_venv_modes_and_drops_extras(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"
    venv_bin = install_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.write_text(f"#!/bin/sh\nexec {install_root}/.venv/bin/python3\n", encoding="utf-8")
    venv_python.chmod(0o755)
    venv_before = venv_python.read_text(encoding="utf-8")
    venv_inode = (install_root / ".venv").stat().st_ino

    legacy = install_root / "server.py"
    legacy.write_text("legacy\n", encoding="utf-8")
    stale = install_root / "runtime" / "mcp" / "stale.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale\n", encoding="utf-8")

    packaging.install_tree(system, install_root)

    # venv не переименовывается и не пересоздаётся: тот же inode, то же
    # содержимое, тот же абсолютный путь внутри shebang-обёрток.
    assert (install_root / ".venv").stat().st_ino == venv_inode
    assert venv_python.read_text(encoding="utf-8") == venv_before
    assert stat.S_IMODE(venv_python.stat().st_mode) == 0o755

    assert not legacy.exists()
    assert not stale.exists()

    installed_entry = install_root / "runtime" / "mcp" / "entry.py"
    source_entry = system / "runtime" / "mcp" / "entry.py"
    assert stat.S_IMODE(installed_entry.stat().st_mode) == stat.S_IMODE(source_entry.stat().st_mode)
    installed_plain = install_root / "runtime" / "mcp" / "server.py"
    source_plain = system / "runtime" / "mcp" / "server.py"
    assert stat.S_IMODE(installed_plain.stat().st_mode) == stat.S_IMODE(source_plain.stat().st_mode)

    assert packaging.verify_install(system, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_real_tree_install_preserves_source_modes(tmp_path):
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(PROJECT_ROOT, install_root)

    for rel in ("runtime/mcp/server.py", "runtime/lib/brain_skill_check.py"):
        source_mode = stat.S_IMODE((PROJECT_ROOT / rel).stat().st_mode)
        installed_mode = stat.S_IMODE((install_root / rel).stat().st_mode)
        assert installed_mode == source_mode, rel

    assert packaging.verify_install(PROJECT_ROOT, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_concurrent_installs_converge_and_never_expose_partial_files(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system, install_root)

    failures: list[BaseException] = []
    results: list[dict] = []
    dirty: list[dict] = []
    stop = threading.Event()

    def installer():
        try:
            for _ in range(4):
                results.append(packaging.install_tree(system, install_root))
        except BaseException as exc:  # pragma: no cover - фиксируем любой сбой
            failures.append(exc)

    def reader():
        while not stop.is_set():
            try:
                report = packaging.verify_install(system, install_root)
            except OSError:
                # Файл исчез между обходом каталога и чтением — это окно
                # подмены, а не полуфабрикат содержимого.
                continue
            if report["mismatches"] or report["extras"]:
                dirty.append(report)

    threads = [threading.Thread(target=installer) for _ in range(4)]
    watcher = threading.Thread(target=reader)
    watcher.start()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stop.set()
    watcher.join()

    assert failures == []
    assert len(results) == 16
    assert all(report["status"] == "ok" for report in results)
    # Полуфабрикат никогда не виден: содержимое собирается в staging, поэтому
    # читатель либо видит валидный файл, либо не видит файла вовсе.
    assert dirty == []
    assert packaging.verify_install(system, install_root)["status"] == "ok"
    assert _internal_leftovers(install_root) == []


def test_verify_ignores_internal_leftovers_and_recover_drops_them(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system, install_root)

    orphan = install_root / (packaging.BACKUP_PREFIX + "orphan")
    (orphan / "runtime" / "mcp").mkdir(parents=True)
    (orphan / "runtime" / "mcp" / "server.py").write_text("# stale backup\n", encoding="utf-8")

    assert packaging.verify_install(system, install_root)["status"] == "ok"

    report = packaging.recover_install(install_root)

    assert report["recovered"] is False
    assert orphan.name in report["dropped"]
    assert _internal_leftovers(install_root) == []


def test_unreadable_journal_does_not_block_install(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system, install_root)
    (install_root / packaging.JOURNAL_NAME).write_text("{ not json", encoding="utf-8")

    result = packaging.install_tree(system, install_root)

    assert result["status"] == "ok"
    assert not (install_root / packaging.JOURNAL_NAME).exists()
    assert packaging.verify_install(system, install_root)["status"] == "ok"


def test_recover_cli_reports_rollback(tmp_path):
    system = _fake_system_root(tmp_path, "one")
    install_root = tmp_path / "brain-mcp"
    packaging.install_tree(system, install_root)

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "runtime" / "mcp" / "packaging.py"),
            "recover",
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["recovered"] is False
    assert payload["dropped"] == []
