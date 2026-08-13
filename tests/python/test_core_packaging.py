"""t-2026-08-10-core-packaging: одна установка вместо трёх копий.

27 файлов делали собственный трёхпутевой bootstrap sys.path, причём порядок
приоритета отличался от файла к файлу. Установка шла install -m 755 + cp -R в
два каталога сразу, поэтому расхождение версий между установленной и
репозиторной копией было штатным состоянием — и четырежды за одну сессию
давало ложную картину при отладке.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent


def _runtime_files():
    for path in sorted((REPO / "runtime").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def test_no_syspath_bootstrap_left_in_runtime():
    offenders = []
    for path in _runtime_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "sys.path.insert" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"остался bootstrap: {offenders}"


def test_pyproject_declares_packages_and_scripts():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.setuptools.packages.find]" in text
    assert 'package-dir = { "" = "runtime/lib" }' in text
    assert "[project.scripts]" in text
    assert "brain_cli" in text


def test_declared_entry_points_are_importable():
    """Точка входа, которую нельзя импортировать, ломает установку целиком."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    targets = re.findall(r'=\s*"([\w.]+):(\w+)"', section)
    assert targets, "секция [project.scripts] пуста"
    for module, func in targets:
        mod = __import__(module, fromlist=[func])
        assert callable(getattr(mod, func)), f"{module}:{func} не вызывается"


def test_flat_modules_are_all_declared():
    """Незаявленный модуль просто не поедет в установку — и отвалится в проде."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    declared = set(re.findall(r'^\s*"(brain_\w+)",\s*$', text, re.M))
    on_disk = {p.stem for p in (REPO / "runtime" / "lib").glob("*.py")}
    missing = sorted(on_disk - declared)
    assert not missing, f"модули вне pyproject: {missing}"


def test_setup_removes_stale_copies():
    """Пока старые каталоги на месте, они участвуют в разрешении импорта."""
    text = (REPO / "setup-brain-v2.sh").read_text(encoding="utf-8")
    assert 'rm -rf "$HOME/.local/lib/brain" "$HOME/.local/share/brain/lib"' in text
    assert "pip install --user -e" in text
    assert "brain-runtime.pth" in text, "нужен запасной путь: pip отказывает при PEP 668"


def test_brain_status_reports_core_version():
    text = (REPO / "runtime" / "bin" / "brain-status").read_text(encoding="utf-8")
    assert "core_version()" in text and "core_location()" in text


def test_core_version_module():
    from brain_core.version import core_location, core_version

    assert isinstance(core_version(), str) and core_version()
    assert Path(core_location()).is_dir()


def test_embedded_python_heredocs_are_valid():
    """bash -n не заглядывает внутрь heredoc: там уже ломалось при чистке."""
    broken = []
    for path in _runtime_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in re.finditer(r"<<-?'?(PY[A-Z]*|PYEOF)'?\n(.*?)\n\1\n", text, re.S):
            try:
                compile(m.group(2), f"{path}:heredoc", "exec")
            except SyntaxError as exc:
                broken.append(f"{path.relative_to(REPO)}: {exc}")
    assert broken == [], broken
