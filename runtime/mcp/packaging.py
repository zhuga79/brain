#!/usr/bin/env python3
"""Install and verify the managed Brain MCP runtime tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Iterable


MANAGED_ROOTS = ("runtime/mcp", "runtime/lib")
MANIFEST_NAME = "manifest.json"
EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
PRESERVED_TOP_LEVEL = {".venv"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_source_files(system_root: Path) -> Iterable[Path]:
    for root_name in MANAGED_ROOTS:
        root = system_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIRS for part in path.relative_to(system_root).parts):
                continue
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            yield path


def source_manifest(system_root: Path) -> dict:
    files = {
        str(path.relative_to(system_root)): _sha256(path)
        for path in _iter_source_files(system_root)
    }
    return {
        "schema": "brain-mcp-install-manifest-v1",
        "files": files,
        "file_count": len(files),
    }


def _installed_files(install_root: Path) -> list[str]:
    files: list[str] = []
    if not install_root.exists():
        return files
    for path in sorted(install_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(install_root)
        if rel.parts and rel.parts[0] == ".venv":
            continue
        if rel.name == MANIFEST_NAME:
            continue
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(str(rel))
    return files


def _reset_install_root(install_root: Path) -> None:
    install_root.mkdir(parents=True, exist_ok=True)
    for child in install_root.iterdir():
        if child.name in PRESERVED_TOP_LEVEL:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def install_tree(system_root: Path, install_root: Path) -> dict:
    manifest = source_manifest(system_root)
    _reset_install_root(install_root)
    for rel_path in manifest["files"]:
        source = system_root / rel_path
        target = install_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    manifest_path = install_root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"status": "ok", **manifest}


def verify_install(system_root: Path, install_root: Path) -> dict:
    manifest = source_manifest(system_root)
    expected = manifest["files"]
    present = _installed_files(install_root)
    present_set = set(present)
    expected_set = set(expected)
    missing = [{"path": path} for path in sorted(expected_set - present_set)]
    extras = [{"path": path} for path in sorted(present_set - expected_set)]
    mismatches = []
    for path in sorted(expected_set & present_set):
        installed = install_root / path
        digest = _sha256(installed)
        if digest != expected[path]:
            mismatches.append({"path": path, "expected": expected[path], "installed": digest})
    drift_count = len(missing) + len(extras) + len(mismatches)
    return {
        "status": "ok" if drift_count == 0 else "drift",
        "file_count": manifest["file_count"],
        "missing": missing,
        "extras": extras,
        "mismatches": mismatches,
        "drift_count": drift_count,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or verify the Brain MCP runtime tree")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "verify", "manifest"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--system-root", required=True)
        if name != "manifest":
            sub.add_argument("--install-root", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    system_root = Path(args.system_root).resolve()
    if args.command == "manifest":
        print(json.dumps(source_manifest(system_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    install_root = Path(args.install_root).resolve()
    if args.command == "install":
        print(json.dumps(install_tree(system_root, install_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = verify_install(system_root, install_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
