# tests/lib/wait_for_port.py — общий опрос готовности TCP-порта для смоук-кейсов.
#
# Зачем. `brain-dashboard serve` (и любой другой сервер, поднятый кейсом в
# фоновом потоке/процессе) слушает сокет уже ВНУТРИ своего запуска — bind()
# происходит не до старта потока/процесса, а как часть его же работы. Кейс,
# который стартует сервер и сразу шлёт HTTP-запрос после фиксированной паузы
# (`time.sleep(0.3)`, `sleep 1`), угадывает скорость раннера. На медленном CI
# поток/процесс не успевает забиндиться — запрос падает трассировкой
# ConnectionRefusedError, а не внятным отказом. Ровно этот класс уронил CI
# дважды (t-2026-08-17-ci-flakes-block-the-recheck), и найден третий раз в
# 13-audit-log (t-2026-08-17-audit-log-case-waits-on-host-s).
#
# Вместо паузы — опрос сокета в цикле с дедлайном: пробуем connect(), при
# отказе короткая пауза и повтор, при исчерпании дедлайна — AssertionError с
# понятным текстом вместо трассировки. Образец до выноса сюда — inline-цикл
# в tests/cases/09-dashboard.sh (SSE-кейс).
#
# Используется и в bash-кейсах (через heredoc `python3 - <<'PYEOF'`, добавляя
# `tests/lib` в sys.path), и потенциально в tests/python/*.py.

from __future__ import annotations

import socket
import time


def wait_for_port(
    host: str,
    port: int,
    deadline_s: float = 15.0,
    poll_s: float = 0.05,
    connect_timeout_s: float = 8.0,
) -> socket.socket:
    """Дождаться, пока host:port начнёт принимать TCP-соединения.

    Возвращает уже подключённый сокет (вызывающий код решает, читать ли с
    него напрямую — как 09-dashboard делает для сырого HTTP/1.0 — или
    закрыть и использовать urllib/requests отдельно, как 13-audit-log).

    При исчерпании `deadline_s` кидает AssertionError с внятным текстом —
    это и есть проверяемое свойство («сервис стал доступен»), а не
    предположение о том, сколько именно секунд занимает старт.
    """
    deadline = time.time() + deadline_s
    last_error: Exception | None = None
    while time.time() < deadline:
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        candidate.settimeout(connect_timeout_s)
        try:
            candidate.connect((host, port))
        except OSError as exc:
            last_error = exc
            candidate.close()
            time.sleep(poll_s)
            continue
        return candidate
    raise AssertionError(
        f"service did not start listening on {host}:{port} within {deadline_s}s"
        + (f" (last error: {last_error})" if last_error else "")
    )
