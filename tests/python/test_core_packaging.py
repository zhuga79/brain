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


def test_setup_rewrites_runtime_pth_after_pip():
    """Stale .pth from another checkout stays on sys.path if we write it only on pip failure."""
    text = (REPO / "setup-brain-v2.sh").read_text(encoding="utf-8")
    after_pip = text.split("pip install --user -e", 1)[1]
    fi_idx = after_pip.find("\nfi\n")
    assert fi_idx != -1, "не нашли закрытие ветки pip install"
    assert "brain-runtime.pth" in after_pip[fi_idx:], (
        "перезапись .pth должна идти после if pip, иначе чужой чекаут остаётся в sys.path"
    )


def test_setup_pth_writer_does_not_resolve_checkout():
    """resolve() превращает symlink-чекаут в Документы/Brain/files — status врёт про чужую копию."""
    text = (REPO / "setup-brain-v2.sh").read_text(encoding="utf-8")
    after_pip = text.split("pip install --user -e", 1)[1]
    assert "root = Path(sys.argv[1]).resolve()" not in after_pip
    assert "root = Path(sys.argv[1])" in after_pip


def test_cli_install_runs_after_pip_editable():
    """Обёртки из runtime/bin обязаны пережить console-скрипты pip.

    `pip install -e` создаёт из [project.scripts] свои brain-provider,
    brain-validate и brain-search в том же ~/.local/bin. Пока установка CLI
    шла первой, pip затирал три обёртки — 88-bin-install видел их
    устаревшими. Локально это не проявлялось: PEP 668 гнал pip в .pth-фолбэк,
    console-скриптов не возникало, и гейт был зелёным из-за отказа pip.
    """
    text = (REPO / "setup-brain-v2.sh").read_text(encoding="utf-8")
    pip_at = text.find("pip install --user -e")
    install_at = text.find('install -m 755 "$_cmd_path"')
    assert pip_at != -1 and install_at != -1
    assert pip_at < install_at, (
        "установка CLI обязана идти после pip install -e, иначе console-скрипты "
        "pip перебивают обёртки runtime/bin"
    )


def test_smoke_runner_pins_provider_clis():
    """Состав провайдерских CLI задаёт песочница, а не хост.

    `shutil.which` решал, доступен ли провайдер, поэтому один коммит давал
    100/100 у оператора (codex/gemini/claude/opencode установлены) и 92/100 на
    чистом раннере. Заглушки идут первыми в PATH и перекрывают настоящие CLI.
    """
    runner = (REPO / "tests" / "run.sh").read_text(encoding="utf-8")
    assert "lib/provider-stubs.sh" in runner, "раннер не подключает заглушки провайдеров"
    assert 'export PATH="$STUB_BIN:$PATH"' in runner, "заглушки не в начале PATH"

    stubs = (REPO / "tests" / "lib" / "provider-stubs.sh").read_text(encoding="utf-8")
    for name in ("claude", "codex", "gemini", "opencode"):
        assert name in stubs, f"нет заглушки для {name}"


def test_brain_status_reports_core_version():
    text = (REPO / "runtime" / "bin" / "brain-status").read_text(encoding="utf-8")
    assert "core_version()" in text and "core_location()" in text


def test_core_version_module():
    from brain_core.version import core_location, core_version

    assert isinstance(core_version(), str) and core_version()
    loc = core_location()
    assert Path(loc).is_dir() or loc.endswith(".pth") or loc.startswith("dpkg:")


class _Run:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_core_version_falls_back_to_dpkg_when_metadata_is_blank(monkeypatch):
    """t-2026-08-16-...-s6: the .deb has no dist-info, so dpkg-query answers."""
    import brain_core.version as ver

    monkeypatch.setattr(ver.metadata, "version",
                        lambda _d: (_ for _ in ()).throw(ver.metadata.PackageNotFoundError()))
    monkeypatch.setattr(ver, "_matching_pth", lambda _r: None)
    monkeypatch.setattr(ver, "_distribution_dir", lambda: None)
    monkeypatch.setattr(ver.shutil, "which", lambda _c: "/usr/bin/" + _c)

    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        if cmd[:2] == ["dpkg", "-S"]:
            return _Run(0, f"brain-runtime: {cmd[2]}\n")
        if cmd[:2] == ["dpkg-query", "-W"]:
            return _Run(0, "0.2.0")
        raise AssertionError(cmd)

    monkeypatch.setattr(ver.subprocess, "run", fake_run)
    assert ver.core_version() == "0.2.0"
    assert ver.core_location() == "dpkg:brain-runtime"
    assert ["dpkg", "-S"] == calls[0][:2]


def test_core_version_dpkg_fallback_ignores_a_file_dpkg_does_not_own(monkeypatch):
    import brain_core.version as ver

    monkeypatch.setattr(ver.metadata, "version",
                        lambda _d: (_ for _ in ()).throw(ver.metadata.PackageNotFoundError()))
    monkeypatch.setattr(ver, "_matching_pth", lambda _r: None)
    monkeypatch.setattr(ver.shutil, "which", lambda _c: "/usr/bin/" + _c)
    # dpkg -S: file belongs to no package
    monkeypatch.setattr(ver.subprocess, "run",
                        lambda cmd, **_k: _Run(1, "dpkg-query: no path found matching\n"))
    assert ver.core_version() == "unpackaged"


def test_core_version_dpkg_fallback_noop_without_dpkg(monkeypatch):
    import brain_core.version as ver

    monkeypatch.setattr(ver.metadata, "version",
                        lambda _d: (_ for _ in ()).throw(ver.metadata.PackageNotFoundError()))
    monkeypatch.setattr(ver, "_matching_pth", lambda _r: None)
    monkeypatch.setattr(ver.shutil, "which", lambda _c: None)
    assert ver.core_version() == "unpackaged"


def test_core_location_is_the_import_path():
    """resolve() превращает ~/brain в Документы/Brain/files и status врёт про чужую копию."""
    import brain_core.version as ver

    src = (REPO / "runtime" / "lib" / "brain_core" / "version.py").read_text(encoding="utf-8")
    assert "Path(__file__).resolve()" not in src
    assert ver._import_root() == Path(ver.__file__).parent.parent


def test_pyproject_does_not_set_pytest_pythonpath():
    """PYTHONPATH задают CI, хук и смоук; pythonpath в pyproject маскирует unpackaged."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.pytest.ini_options]", 1)[1].split("\n[", 1)[0]
    assert "pythonpath" not in section


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


# --- t-2026-08-16-multi-user-federation-readines-s5: debian packaging ---

def _control_field(name: str) -> str:
    text = (REPO / "debian" / "control").read_text(encoding="utf-8")
    m = re.search(rf"(?m)^{re.escape(name)}:[ \t]*(.*(?:\n[ \t]+.*)*)", text)
    return m.group(1).strip() if m else ""


def test_debian_skeleton_files_present():
    for rel in ("control", "changelog", "compat", "copyright", "rules",
                "install", "source/format"):
        assert (REPO / "debian" / rel).is_file(), f"debian/{rel} missing"
    assert (REPO / "debian" / "rules").stat().st_mode & 0o111, "debian/rules not executable"
    assert (REPO / "runtime" / "packaging" / "build-deb.sh").stat().st_mode & 0o111


def test_debian_control_declares_arch_all_and_runtime_deps():
    assert _control_field("Package") == "brain-runtime"
    assert _control_field("Architecture") == "all"
    depends = _control_field("Depends")
    assert "python3 (>= 3.10)" in depends
    assert re.search(r"\bgit\b", depends) and re.search(r"\bjq\b", depends)


def test_debian_changelog_version_matches_pyproject():
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject).group(1)
    top = (REPO / "debian" / "changelog").read_text(encoding="utf-8").splitlines()[0]
    m = re.match(r"brain-runtime \(([^)]+)\)", top)
    assert m and m.group(1) == version, f"changelog {top!r} != pyproject {version}"


def test_debian_install_lists_only_existing_paths():
    for line in (REPO / "debian" / "install").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        src = line.split()[0]
        assert (REPO / src).exists(), f"debian/install names missing {src}"


def test_build_deb_script_does_not_touch_an_installed_tree():
    text = (REPO / "runtime" / "packaging" / "build-deb.sh").read_text(encoding="utf-8")
    assert ".local/" not in text and "$HOME/.local" not in text
