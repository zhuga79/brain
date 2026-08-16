"""t-2026-08-14-system-guard-depends-on-self-d: опознание того, кто коммитит.

Класс B2 по `doctrine/review-exit-criteria.md`: отсутствие идентичности давало
привилегию. `pre-commit-system-guard` считал агентом того, у кого выставлена
`BRAIN_AGENT_ID`, а человеком — всех остальных, поэтому агент, не выставивший
переменную, писал в системный слой `master` беспрепятственно: так прошли два
коммита 14 и 15 августа 2026.

Инвариант, который держат эти тесты: в главной ветке системный путь коммитит
только положительно опознанный оператор. Ни «нет переменной», ни «проверка не
выполнилась» человеком не считаются.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from brain_core.committer import (
    DEFAULT_SESSION_TTL,
    classify_committer,
    operator_session_path,
    operator_session_state,
    session_ttl,
)

REPO = Path(__file__).resolve().parent.parent.parent
GUARD = REPO / "runtime" / "hooks" / "pre-commit-system-guard"


# ── Опознание как чистая функция ────────────────────────────────────────────

def test_agent_id_identifies_an_agent():
    who = classify_committer(env={"BRAIN_AGENT_ID": "claude-opus-p1-c58e"})
    assert who.is_agent
    assert who.name == "claude-opus-p1-c58e"


def test_agent_stays_an_agent_at_a_terminal():
    """Самообъявление сужает права, поэтому терминал его не отменяет."""
    who = classify_committer(env={"BRAIN_AGENT_ID": "gemini-pro-ab12"}, interactive=True)
    assert who.is_agent


def test_absence_of_agent_id_is_not_a_human(tmp_path):
    """Сердцевина находки: «переменной нет» — это НЕ признак человека."""
    env = {"BRAIN_OPERATOR_SESSION": str(tmp_path / "нет-такого")}
    who = classify_committer(env=env)
    assert who.is_unidentified
    assert not who.is_operator


def test_blank_agent_id_is_not_a_human(tmp_path):
    env = {"BRAIN_AGENT_ID": "   ", "BRAIN_OPERATOR_SESSION": str(tmp_path / "нет")}
    assert classify_committer(env=env).is_unidentified


def test_interactive_terminal_identifies_the_operator(tmp_path):
    env = {"BRAIN_OPERATOR_SESSION": str(tmp_path / "нет"), "USER": "blqd"}
    who = classify_committer(env=env, interactive=True)
    assert who.is_operator
    assert who.name == "blqd"
    assert "терминал" in who.evidence


def test_fresh_session_identifies_the_operator(tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    who = classify_committer(env={"BRAIN_OPERATOR_SESSION": str(session)})
    assert who.is_operator
    assert str(session) in who.evidence


def test_stale_session_is_not_identity(tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    old = time.time() - DEFAULT_SESSION_TTL - 60
    os.utime(session, (old, old))
    who = classify_committer(env={"BRAIN_OPERATOR_SESSION": str(session)})
    assert who.is_unidentified
    assert "истекла" in who.note


def test_world_writable_session_is_rejected(tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    session.chmod(0o666)
    fresh, reason = operator_session_state(session)
    assert not fresh
    assert "всем" in reason


def test_group_writable_session_is_accepted(tmp_path):
    """Обычный umask 002 делает `touch` груповой записью — это не угроза."""
    session = tmp_path / "operator-session"
    session.touch()
    session.chmod(0o664)
    fresh, _ = operator_session_state(session)
    assert fresh


def test_session_of_another_user_is_rejected(tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    fresh, reason = operator_session_state(session, uid=os.getuid() + 1)
    assert not fresh
    assert "пользовател" in reason


def test_session_directory_is_not_identity(tmp_path):
    fresh, reason = operator_session_state(tmp_path)
    assert not fresh
    assert "файл" in reason


def test_session_symlink_is_not_identity(tmp_path):
    target = tmp_path / "real"
    target.touch()
    link = tmp_path / "operator-session"
    link.symlink_to(target)
    fresh, reason = operator_session_state(link)
    assert not fresh
    assert "ссылка" in reason


# ── Расположение и срок сессии ──────────────────────────────────────────────

def test_session_path_prefers_runtime_dir():
    got = operator_session_path({"XDG_RUNTIME_DIR": "/run/user/1000", "HOME": "/home/x"})
    assert got == Path("/run/user/1000/brain/operator-session")


def test_session_path_falls_back_to_cache():
    got = operator_session_path({"HOME": "/home/x"})
    assert got == Path("/home/x/.cache/brain/operator-session")


def test_session_path_honours_explicit_override():
    got = operator_session_path({"BRAIN_OPERATOR_SESSION": "/tmp/s", "HOME": "/home/x"})
    assert got == Path("/tmp/s")


@pytest.mark.parametrize("raw,expected", [
    ("60", 60), ("", DEFAULT_SESSION_TTL), ("мусор", DEFAULT_SESSION_TTL),
    ("0", DEFAULT_SESSION_TTL), ("-5", DEFAULT_SESSION_TTL),
])
def test_session_ttl_parsing(raw, expected):
    assert session_ttl({"BRAIN_OPERATOR_SESSION_TTL": raw}) == expected


# ── Гейт целиком ────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _guard_env(home: Path, session: Path, **extra: str) -> dict:
    """Окружение хука без наследования: прогон не должен зависеть от шелла.

    pre-commit гоняет pytest с выставленной BRAIN_AGENT_ID — унаследуй тест
    окружение, и он проверял бы агентскую ветку кода вместо неопознанной.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "BRAIN_OPERATOR_SESSION": str(session),
    }
    env.update(extra)
    return env


@pytest.fixture
def guarded_repo(tmp_path):
    """Репозиторий на master с системным файлом в индексе."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "case@example.invalid")
    _git(repo, "config", "user.name", "case")
    (repo / "README.md").write_text("база\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "база")
    (repo / "runtime").mkdir()
    (repo / "runtime" / "brain-task").write_text("правка рантайма\n", encoding="utf-8")
    _git(repo, "add", "runtime/brain-task")
    return repo


def _run_guard(repo: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(GUARD)], cwd=repo, env=env, capture_output=True, text=True,
    )


@pytest.mark.integration
def test_guard_refuses_commit_without_any_identity(guarded_repo, tmp_path):
    """Воспроизведение обхода: до правки этот прогон возвращал 0."""
    env = _guard_env(tmp_path / "home", tmp_path / "нет-сессии")
    done = _run_guard(guarded_repo, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "неопознанный процесс" in done.stderr
    assert "runtime/brain-task" in done.stderr


@pytest.mark.integration
def test_guard_names_the_branch_for_a_declared_agent(guarded_repo, tmp_path):
    env = _guard_env(
        tmp_path / "home", tmp_path / "нет-сессии",
        BRAIN_AGENT_ID="claude-opus-p1-c58e", BRAIN_TASK_ID="t-smoke",
    )
    done = _run_guard(guarded_repo, env)
    assert done.returncode == 1
    assert "agent/t-smoke" in done.stderr


@pytest.mark.integration
def test_guard_lets_the_operator_through_on_a_fresh_session(guarded_repo, tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    done = _run_guard(guarded_repo, _guard_env(tmp_path / "home", session))
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.integration
def test_guard_refuses_on_a_stale_session(guarded_repo, tmp_path):
    session = tmp_path / "operator-session"
    session.touch()
    old = time.time() - DEFAULT_SESSION_TTL - 60
    os.utime(session, (old, old))
    done = _run_guard(guarded_repo, _guard_env(tmp_path / "home", session))
    assert done.returncode == 1
    assert "истекла" in done.stderr


@pytest.mark.integration
def test_guard_ignores_the_data_layer(guarded_repo, tmp_path):
    _git(guarded_repo, "reset", "-q")
    (guarded_repo / "wiki").mkdir()
    (guarded_repo / "wiki" / "page.md").write_text("страница\n", encoding="utf-8")
    _git(guarded_repo, "add", "wiki/page.md")
    done = _run_guard(guarded_repo, _guard_env(tmp_path / "home", tmp_path / "нет"))
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.integration
def test_guard_ignores_task_branches(guarded_repo, tmp_path):
    _git(guarded_repo, "switch", "-q", "-c", "agent/t-smoke")
    done = _run_guard(guarded_repo, _guard_env(tmp_path / "home", tmp_path / "нет"))
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.integration
def test_guard_covers_the_first_commit_of_an_unborn_branch(tmp_path):
    """rev-parse на неродившейся ветке падал, имя ветки выходило пустым."""
    repo = tmp_path / "fresh"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "case@example.invalid")
    _git(repo, "config", "user.name", "case")
    (repo / "runtime").mkdir()
    (repo / "runtime" / "thing").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "runtime/thing")
    done = _run_guard(repo, _guard_env(tmp_path / "home", tmp_path / "нет"))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "runtime/thing" in done.stderr


@pytest.mark.integration
def test_main_branches_env_cannot_unprotect_master(guarded_repo, tmp_path):
    """Переменная список защищённых веток расширяет, но не подменяет."""
    env = _guard_env(tmp_path / "home", tmp_path / "нет", BRAIN_MAIN_BRANCHES="trunk")
    done = _run_guard(guarded_repo, env)
    assert done.returncode == 1, done.stdout + done.stderr


@pytest.mark.integration
def test_main_branches_env_extends_the_protected_set(guarded_repo, tmp_path):
    _git(guarded_repo, "switch", "-q", "-c", "trunk")
    env = _guard_env(tmp_path / "home", tmp_path / "нет", BRAIN_MAIN_BRANCHES="trunk")
    done = _run_guard(guarded_repo, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "trunk" in done.stderr


@pytest.mark.integration
def test_guard_fails_closed_when_it_cannot_check(guarded_repo, tmp_path):
    """Молчаливый пропуск при осечке проверки неотличим от снятого гейта."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stub = fake_bin / "python3"
    stub.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    stub.chmod(0o755)
    env = _guard_env(
        tmp_path / "home", tmp_path / "нет",
        BRAIN_AGENT_ID="claude-opus-p1-c58e",
    )
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    done = _run_guard(guarded_repo, env)
    assert done.returncode == 1
    assert "не смог проверить" in done.stderr


def test_guard_does_not_treat_a_missing_variable_as_a_human():
    """Инвариант на исходнике: ранний выход по пустой BRAIN_AGENT_ID запрещён."""
    text = GUARD.read_text(encoding="utf-8")
    assert "classify_committer" in text
    assert '[ -n "$AGENT" ] || exit 0' not in text
    assert "PYTHONPATH" in text, "гейт обязан находить brain_core без установки"
