"""t-2026-08-17-audit-log-case-waits-on-host-s: ожидание готовности порта.

Помощник заменил фиксированные паузы в смоук-кейсах. Пауза — предположение о
скорости раннера, и проверить её нечем: она либо достаточна на этой машине,
либо нет, и узнаётся это только по красному CI. Опрос проверяется:
дожидается ли он сервиса, поднявшегося позже любой разумной паузы, и
отказывает ли внятно, когда сервиса нет вовсе.

Оба свойства держатся тестом, а не разовым прогоном рукой: иначе следующая
правка помощника (шаг опроса, таймаут connect, порядок закрытия сокета)
пройдёт без сигнала.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))

from wait_for_port import require_port, wait_for_port  # noqa: E402


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_waits_for_a_service_that_binds_later():
    """Сервис, поднявшийся позже любой прежней паузы, всё равно дожидается.

    0.7 с — больше и прежнего sleep(0.3) из 13-audit-log, и sleep(0.5) из
    09-dashboard: на этом сценарии обе прежние конструкции дали бы
    ConnectionRefusedError. Это и есть инверсия доказательства.
    """
    port = _free_port()
    ready = threading.Event()

    def serve():
        time.sleep(0.7)
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        ready.set()
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass
        srv.close()

    thread = threading.Thread(target=serve, daemon=True)
    started = time.time()
    thread.start()

    sock = wait_for_port("127.0.0.1", port, deadline_s=10)
    waited = time.time() - started
    sock.close()

    assert ready.is_set()
    # Не проскочил случайно раньше, чем сервис забиндился.
    assert waited >= 0.6, f"подключение произошло через {waited:.2f}с, до bind()"
    thread.join(timeout=5)


def test_refuses_when_nothing_listens():
    port = _free_port()  # свободен и никем не занят — connect обязан отказать
    started = time.time()
    with pytest.raises(AssertionError) as exc:
        wait_for_port("127.0.0.1", port, deadline_s=0.3)
    elapsed = time.time() - started

    message = str(exc.value)
    assert f"127.0.0.1:{port}" in message
    assert "0.3s" in message
    # Отказ по дедлайну, а не мгновенный: опрос действительно шёл.
    assert 0.3 <= elapsed < 5


def test_require_port_fails_like_the_rest_of_a_smoke_case(tmp_path):
    """Отказ — одна строка `FAILED: ...` и код 1, а не трассировка.

    Прочие проверки смоук-кейсов отказывают именно так. Если ожидание порта
    отказывает трассировкой, диагностика кейса зависит от того, какая из его
    проверок упала, — и оператор читает служебный кадр вместо причины.
    """
    port = _free_port()
    script = tmp_path / "case.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(LIB)!r})\n"
        "from wait_for_port import require_port\n"
        f"require_port('127.0.0.1', {port}, deadline_s=0.3)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=30
    )

    assert proc.returncode == 1
    assert proc.stdout.startswith("FAILED: ")
    assert proc.stdout.count("\n") == 1, f"ожидалась одна строка, получено: {proc.stdout!r}"
    assert "Traceback" not in proc.stderr and not proc.stderr.strip()
