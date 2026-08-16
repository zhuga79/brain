"""Кто стоит за коммитом: агент, оператор или никто.

Гейт системного слоя (`runtime/hooks/pre-commit-system-guard`) до 16 августа
2026 считал агентом того, у кого выставлена `BRAIN_AGENT_ID`, а человеком —
всех остальных. То есть признаком человека служило ОТСУТСТВИЕ переменной,
которую нарушитель выставляет себе сам. 14 и 15 августа два агентских коммита
ушли в `master` именно так, и заметили это случайно.

Здесь идентичность собирается из признаков, которые процесс себе не назначает
объявлением:

* **интерактивный терминал** — свойство дескрипторов процесса, а не окружения:
  чтобы его подделать, агентской обвязке нужно осознанно выделить pty;
* **операторская сессия** — файл вне репозитория, который человек заводит
  руками (`touch`) и который сам протухает по TTL.

Абсолютной границы тут нет и быть не может: агент работает от того же
пользователя, с тем же `HOME` и тем же доступом к файловой системе. Задача
рубежа другая — чтобы обход требовал осознанного действия, а не забывчивости.
Поэтому третий исход, «не опознан», трактуется вызывающей стороной как отказ, а
не как человек: отсутствие идентичности не даёт привилегий.
"""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

AGENT = "agent"
OPERATOR = "operator"
UNIDENTIFIED = "unidentified"

DEFAULT_SESSION_TTL = 900
"""Пятнадцать минут: хватает на серию коммитов из GUI-клиента и не превращает
разовое подтверждение человека в постоянно открытую дверь."""

SESSION_RELPATH = ("brain", "operator-session")


@dataclass(frozen=True)
class Committer:
    """Итог опознания: род, имя (если известно) и на чём вывод держится."""

    kind: str
    name: str = ""
    evidence: str = ""
    note: str = ""

    @property
    def is_agent(self) -> bool:
        return self.kind == AGENT

    @property
    def is_operator(self) -> bool:
        return self.kind == OPERATOR

    @property
    def is_unidentified(self) -> bool:
        return self.kind == UNIDENTIFIED


def _env(env: dict | None) -> dict:
    return os.environ if env is None else env


def operator_session_path(env: dict | None = None) -> Path:
    """Файл операторской сессии.

    По умолчанию — в `XDG_RUNTIME_DIR` (tmpfs, чистится при выходе из сессии),
    иначе в `~/.cache`. Путь переопределяется `BRAIN_OPERATOR_SESSION`; это
    удобство тестов и нестандартных установок, а не рубеж: переменную видит и
    агент. Рубеж — необходимость осознанно создать свежий файл.
    """
    environ = _env(env)
    explicit = (environ.get("BRAIN_OPERATOR_SESSION") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    runtime_dir = (environ.get("XDG_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        return Path(runtime_dir).expanduser().joinpath(*SESSION_RELPATH)
    home = (environ.get("HOME") or "").strip() or os.path.expanduser("~")
    return Path(home).expanduser().joinpath(".cache", *SESSION_RELPATH)


def session_ttl(env: dict | None = None) -> int:
    """Срок годности операторской сессии в секундах."""
    raw = (_env(env).get("BRAIN_OPERATOR_SESSION_TTL") or "").strip()
    try:
        ttl = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL
    return ttl if ttl > 0 else DEFAULT_SESSION_TTL


def operator_session_state(
    path: Path,
    *,
    ttl: int = DEFAULT_SESSION_TTL,
    now: float | None = None,
    uid: int | None = None,
) -> tuple[bool, str]:
    """Годна ли операторская сессия. Возвращает `(годна, причина)`.

    Проверяется свежесть по mtime и владелец. Из прав отсекается только запись
    для всех: файл, в который пишет любой, ничего не подтверждает. Групповая
    запись допускается сознательно — при типичном umask 002 её ставит обычный
    `touch`, а угрозы за ней нет: сессию подделывает не сосед по группе, а
    процесс того же пользователя, которому права не мешают вовсе.
    """
    owner = os.getuid() if uid is None else uid
    try:
        info = path.lstat()
    except OSError:
        return False, "файла нет"
    if stat.S_ISLNK(info.st_mode):
        return False, "символическая ссылка"
    if not stat.S_ISREG(info.st_mode):
        return False, "не обычный файл"
    if info.st_uid != owner:
        return False, "принадлежит другому пользователю"
    if info.st_mode & 0o002:
        return False, "доступен на запись всем"
    moment = time.time() if now is None else now
    age = int(moment - info.st_mtime)
    if age > ttl:
        return False, f"истекла: обновлена {age} с назад при пределе {ttl} с"
    return True, f"обновлена {max(age, 0)} с назад"


def operator_name(env: dict | None = None) -> str:
    environ = _env(env)
    return (environ.get("USER") or environ.get("LOGNAME") or "").strip()


def classify_committer(
    *,
    env: dict | None = None,
    interactive: bool = False,
    now: float | None = None,
    uid: int | None = None,
) -> Committer:
    """Опознать того, кто коммитит.

    `interactive` вычисляет вызывающая сторона: у git-хука это наличие
    терминала на fd 1/2 (stdin git отвязывает от терминала сам).

    Порядок намеренный. Агент, назвавшийся агентом, остаётся агентом при любых
    прочих признаках: самообъявление сужает права, а не расширяет, и запрещать
    его незачем. Дальше идут положительные признаки человека. Если ни одного —
    «не опознан», и это НЕ человек.
    """
    environ = _env(env)
    agent = (environ.get("BRAIN_AGENT_ID") or "").strip()
    if agent:
        return Committer(AGENT, agent, "переменная BRAIN_AGENT_ID")

    if interactive:
        return Committer(OPERATOR, operator_name(environ), "интерактивный терминал")

    path = operator_session_path(environ)
    ttl = session_ttl(environ)
    fresh, reason = operator_session_state(path, ttl=ttl, now=now, uid=uid)
    if fresh:
        return Committer(
            OPERATOR, operator_name(environ), f"операторская сессия {path} ({reason})"
        )
    return Committer(UNIDENTIFIED, "", "", note=f"{path}: {reason}")
