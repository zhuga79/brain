"""t-2026-08-14-public-ci: PR в master валится красным CI, без именного denylist."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
README = REPO / "README.md"

# Именные правила и секреты — персональные данные. В публичный CI
# их тащить нельзя: список сущностей сам является утечкой.
FORBIDDEN_CI = (
    ".publish-secrets",
    "PII_PATTERN",
    "BRAIN_PUBLISH_SECRETS",
    ".secrets/",
    "named-denylist",
)


def _workflow_files():
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, "нет .github/workflows/*.yml"
    return files


def _workflow_texts():
    return [(path, path.read_text(encoding="utf-8")) for path in _workflow_files()]


def _combined():
    return "\n".join(text for _, text in _workflow_texts())


def test_workflow_triggers_on_push_and_pr_to_master():
    text = _combined()
    assert "pull_request" in text, "workflow не подписан на pull_request"
    assert "push" in text, "workflow не подписан на push"
    assert "master" in text, "workflow не привязан к master"


def test_workflow_runs_tests_run_sh():
    assert "tests/run.sh" in _combined()


def test_workflow_installs_pytest_before_smoke():
    """Кейс 92 гоняет pre-commit-хук, а тот зовёт pytest внутри песочницы.

    Пока установки не было, смоук падал на «No module named pytest», и до шага
    с самим pytest прогон не доходил. Порядок шагов — часть контракта гейта.
    """
    for path, text in _workflow_texts():
        if "tests/run.sh" not in text:
            continue
        install = text.find("pip install pytest")
        assert install != -1, (
            f"{path.relative_to(REPO)}: pytest не ставится, кейс 92 упадёт в песочнице"
        )
        smoke = text.find("bash tests/run.sh")
        assert install < smoke, (
            f"{path.relative_to(REPO)}: pytest ставится после tests/run.sh"
        )
        assert "pip install --user pytest" not in text, (
            f"{path.relative_to(REPO)}: --user не виден из песочницы — "
            "tests/run.sh подменяет HOME"
        )


def test_workflow_runs_full_pytest_suite():
    text = _combined()
    assert "pytest" in text
    assert "PYTHONPATH=runtime/lib" in text


def test_workflow_runs_brain_guard_generic_only():
    text = _combined()
    assert "brain-guard" in text
    assert "--generic-only" in text


def test_required_checks_fail_the_pr():
    """Падение tests/run.sh или brain-guard должно валить job, а не быть advisory."""
    for path, text in _workflow_texts():
        assert "continue-on-error" not in text, (
            f"{path.relative_to(REPO)}: continue-on-error делает падение неблокирующим"
        )


def _code_only(text: str) -> str:
    """Комментарии могут объяснять запрет — смотрим только исполняемые строки."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_ci_does_not_embed_secrets_or_named_denylist():
    for path, text in _workflow_texts():
        code = _code_only(text)
        lowered = code.lower()
        for needle in FORBIDDEN_CI:
            assert needle.lower() not in lowered, (
                f"{path.relative_to(REPO)} тащит в CI запрещённое: {needle}"
            )
        assert "secrets:" not in lowered, (
            f"{path.relative_to(REPO)} пробрасывает GitHub secrets в CI"
        )


def test_readme_links_to_ci():
    text = README.read_text(encoding="utf-8")
    has_badge = "actions/workflows" in text and "badge.svg" in text
    has_link = "github.com/Blqd/brain/actions" in text
    assert has_badge or has_link, "в README нет бейджа или ссылки на Actions"
