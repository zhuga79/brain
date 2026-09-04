"""Версия ядра — одна на установку.

Нужна, чтобы отличить «правка не действует, потому что неверна» от «правка не
действует, потому что исполняется другая копия». До перехода на пакет копий
было три (дерево, ~/.local/lib/brain, ~/.local/share/brain/lib), и разойтись
они могли молча.
"""

from __future__ import annotations

import re
import shutil
import site
import subprocess
from importlib import metadata
from pathlib import Path

DISTRIBUTION = "brain-runtime"
PTH_NAME = "brain-runtime.pth"
DPKG_PACKAGE = "brain-runtime"


def _import_root() -> Path:
    return Path(__file__).parent.parent


def _site_dirs() -> list[Path]:
    dirs: list[Path] = []
    seen: set[str] = set()
    candidates: list[str] = []
    try:
        user = site.getusersitepackages()
        if user:
            candidates.append(user)
    except Exception:
        pass
    try:
        candidates.extend(site.getsitepackages())
    except Exception:
        pass
    for raw in candidates:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        dirs.append(Path(raw))
    return dirs


def _same_dir(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def _matching_pth(root: Path) -> Path | None:
    """Editable .pth, который указывает на каталог текущего импорта."""
    for directory in _site_dirs():
        pth = directory / PTH_NAME
        if not pth.is_file():
            continue
        try:
            text = pth.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("import "):
                continue
            if _same_dir(Path(stripped), root):
                return pth
    return None


def _distribution_dir() -> Path | None:
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None
    located = Path(str(dist.locate_file("")))
    name = located.name
    if name.endswith(".dist-info") or name.endswith(".egg-info"):
        return located.parent
    return located


def _version_from_pyproject(root: Path) -> str | None:
    pyproject = root.parent.parent / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _dpkg_version_owning(path: Path) -> str | None:
    """Version of the .deb that ships ``path``, or None.

    The .deb drops the library straight into dist-packages — no ``.dist-info``,
    so ``importlib.metadata`` is blind to it. ``dpkg -S`` confirms the file
    belongs to brain-runtime before ``dpkg-query`` reports the version, so a
    source checkout on a machine that also has the package installed is not
    mistaken for the package.
    """
    if not shutil.which("dpkg-query") or not shutil.which("dpkg"):
        return None
    try:
        owns = subprocess.run(
            ["dpkg", "-S", str(path)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if owns.returncode != 0 or not owns.stdout.startswith(f"{DPKG_PACKAGE}:"):
        return None
    try:
        res = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", DPKG_PACKAGE],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def core_version() -> str:
    """Версия установленного пакета. `unpackaged`, если установки нет.

    PEP 668 часто блокирует `pip install --user -e`. Тогда setup пишет
    `brain-runtime.pth` в user site — это и есть установка. Пакет .deb кладёт
    библиотеку в dist-packages без dist-info — версию тогда даёт dpkg-query.
    """
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        pass
    root = _import_root()
    if _matching_pth(root) is not None:
        return _version_from_pyproject(root) or "editable"
    dpkg_version = _dpkg_version_owning(Path(__file__))
    if dpkg_version:
        return dpkg_version
    return "unpackaged"


def core_location() -> str:
    """Путь установки: editable .pth, site-packages или каталог импорта.

    Без resolve(): ~/brain — симлинк на Документы/Brain/files, и канонический
    путь выглядит как «unpackaged-копия в приватном дереве», хотя это то же
    дерево, откуда импортировали.
    """
    root = _import_root()
    pth = _matching_pth(root)
    if pth is not None:
        return str(pth)
    dist_dir = _distribution_dir()
    if dist_dir is not None:
        return str(dist_dir)
    if _dpkg_version_owning(Path(__file__)):
        return f"dpkg:{DPKG_PACKAGE}"
    return str(root)
