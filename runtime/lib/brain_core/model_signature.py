"""Единая политика подписи модели при закрытии задачи.

Нормальное закрытие (CLI, MCP, dashboard, app queue, workspace) требует
versioned идентификатор вида `provider-model-version`, например
`openai-gpt-5.4`, `claude-opus-4-8`, `gemini-2.5-pro`, `grok-4.6`.

`unsigned` — legacy escape hatch: только явный opt-in
(`--allow-unsigned` или `BRAIN_ALLOW_UNSIGNED_MODEL=1`) и обязательный
audit `model-unsigned` в журнале. Адаптеры не подставляют `unsigned`
молча. Архивные записи с уже проставленным `model:` (включая исторический
`unsigned`) модуль не перечитывает и не бракует.

`BRAIN_REQUIRE_MODEL` больше не переключает политику: требование подписи
стало умолчанием, а не флагом.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Mapping

UNSIGNED_TOKEN = "unsigned"
ALLOW_UNSIGNED_ENV = "BRAIN_ALLOW_UNSIGNED_MODEL"
AGENT_MODEL_ENV = "BRAIN_AGENT_MODEL"
AUDIT_OP = "model-unsigned"

MODEL_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+$")
MODEL_VERSION_RE = re.compile(r"(?:^|[.-])\d+(?:[.-]\d+)*(?:$|[.-])")
MODEL_PLACEHOLDER_TOKENS = {
    "unsigned", "placeholder", "summary", "cleanup", "todo", "unknown",
    "example", "sample", "dummy", "none", "null", "unset",
}

_TRUTHY = {"1", "true", "yes", "on"}


class ModelSignatureError(ValueError):
    """Модель не проходит политику подписи."""


@dataclass(frozen=True)
class ResolvedModel:
    value: str
    unsigned: bool
    source: str

    @property
    def audit_extra(self) -> str:
        return f"model={self.value} hatch={self.source}"


def env_flag(name: str, environ: Mapping[str, str] | None = None) -> bool:
    raw = (environ if environ is not None else os.environ).get(name, "")
    return str(raw).strip().lower() in _TRUTHY


def validate_model_signature(model: str) -> str:
    """Вернуть очищенную versioned подпись или поднять ModelSignatureError.

    Принимает `openai-gpt-5.4`, `claude-opus-4-8`, `gemini-2.5-pro`,
    `grok-4.6`. Отвергает пустое, placeholder, `unsigned` и значения без
    числовой версии.
    """
    cleaned = str(model or "").strip()
    if not cleaned:
        raise ModelSignatureError("real model required")
    lowered = cleaned.lower()
    tokens = {token for token in re.split(r"[.-]+", lowered) if token}
    if tokens & MODEL_PLACEHOLDER_TOKENS:
        raise ModelSignatureError("real model required")
    if " " in cleaned or not MODEL_SIGNATURE_RE.match(cleaned):
        raise ModelSignatureError("model signature format invalid")
    if not MODEL_VERSION_RE.search(cleaned):
        raise ModelSignatureError("model signature must include numeric version")
    return cleaned


def resolve_completion_model(
    model: str = "",
    *,
    allow_unsigned: bool = False,
    environ: Mapping[str, str] | None = None,
) -> ResolvedModel:
    """Резолв модели для записи в done-блок.

    Порядок: явный аргумент, затем `$BRAIN_AGENT_MODEL`. Пустое значение
    или литерал `unsigned` проходят только через hatch. Versioned значение
    из env побеждает hatch.
    """
    env = environ if environ is not None else os.environ
    explicit = str(model or "").strip()
    if explicit:
        candidate, source = explicit, "argument"
    else:
        fallback = str(env.get(AGENT_MODEL_ENV, "") or "").strip()
        candidate, source = fallback, AGENT_MODEL_ENV if fallback else "argument"

    hatch = bool(allow_unsigned) or env_flag(ALLOW_UNSIGNED_ENV, env)
    if not candidate or candidate.lower() == UNSIGNED_TOKEN:
        if hatch:
            return ResolvedModel(UNSIGNED_TOKEN, True, "allow-unsigned")
        if not candidate:
            raise ModelSignatureError(
                "model signature required: pass --model <provider-model-version> "
                f"or set {AGENT_MODEL_ENV}"
            )
        raise ModelSignatureError("real model required")
    return ResolvedModel(validate_model_signature(candidate), False, source)


def complete_cli_argv(
    task_id: str,
    agent: str,
    model: str = "",
    *,
    allow_unsigned: bool = False,
) -> list[str]:
    """Аргументы `brain-task complete` без молчаливой подстановки unsigned."""
    args = ["complete", str(task_id), "--as", str(agent)]
    cleaned = str(model or "").strip()
    if cleaned:
        args += ["--model", cleaned]
    if allow_unsigned:
        args.append("--allow-unsigned")
    return args


def queue_action_argv(
    action: str,
    task_id: str,
    agent: str,
    *,
    model: str = "",
    allow_unsigned: bool = False,
    reason: str = "",
) -> list[str]:
    """Аргументы brain-task для dashboard/shell-адаптера."""
    if action == "block":
        return ["block", str(task_id), reason or "blocked via dashboard"]
    if action == "complete":
        return complete_cli_argv(
            task_id, agent, model, allow_unsigned=allow_unsigned,
        )
    return [action, str(task_id), "--as", str(agent)]


def _main(argv: list[str]) -> int:
    """CLI для bash-слоя: resolve [--model M] [--allow-unsigned]."""
    import argparse

    parser = argparse.ArgumentParser(prog="brain_core.model_signature")
    sub = parser.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve")
    res.add_argument("--model", default="")
    res.add_argument("--allow-unsigned", action="store_true")
    args = parser.parse_args(argv)
    try:
        resolved = resolve_completion_model(
            args.model, allow_unsigned=args.allow_unsigned,
        )
    except ModelSignatureError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if resolved.unsigned:
        print(
            f"WARN: recording {UNSIGNED_TOKEN} via explicit unsigned hatch",
            file=sys.stderr,
        )
    print(resolved.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
