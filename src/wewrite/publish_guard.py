"""Deterministic authorization gate for remote WeChat draft writes."""

from __future__ import annotations

from pathlib import Path

from .paths import home
from .runs import load_run, set_publish_permission


class PublishAuthorizationError(ValueError):
    """Raised when a remote write has not passed the runtime safety gate."""


def _artifact_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = home() / path
    return path.resolve()


def inspect_publish_authorization(
    input_path: str | Path,
    *,
    direct_confirmation: bool = False,
    run_id: str | None = None,
) -> dict:
    """Inspect publish authorization without consuming one-shot permission."""
    if direct_confirmation:
        return {
            "authorized": True,
            "mode": "direct",
            "run_id": None,
            "reason": None,
        }

    try:
        state = load_run(run_id)
    except (FileNotFoundError, ValueError):
        return {
            "authorized": False,
            "mode": "run",
            "run_id": None,
            "reason": (
                "no authorized current run; grant run permission or pass "
                "--confirm-publish for standalone use"
            ),
        }

    result = {
        "authorized": False,
        "mode": "run",
        "run_id": state.get("run_id"),
        "reason": None,
    }

    if state.get("status") != "completed":
        result["reason"] = "the current run is not completed"
        return result

    editorial = state.get("editorial") or {}
    if editorial.get("decision") != "pass" or editorial.get("publishable") is not True:
        result["reason"] = "editorial review has not marked the article publishable"
        return result

    if (state.get("permissions") or {}).get("publish") is not True:
        result["reason"] = "explicit publish permission is missing"
        return result

    artifacts = state.get("artifacts") or {}
    allowed_paths = {
        _artifact_path(artifacts[name])
        for name in ("article", "illustrated_article")
        if artifacts.get(name)
    }
    requested_path = Path(input_path).resolve()
    if requested_path not in allowed_paths:
        result["reason"] = "input is not an article artifact of the authorized run"
        return result

    result["authorized"] = True
    return result


def authorize_publish(
    input_path: str | Path,
    *,
    direct_confirmation: bool = False,
    run_id: str | None = None,
) -> dict:
    """Authorize one draft write and consume run-scoped permission.

    Agent-driven publishing must be tied to a completed, reviewed run whose
    explicit publish permission is still present.  Standalone CLI users can
    bypass run state only with ``--confirm-publish``; making that intent part
    of the command keeps remote writes visible in shell history.
    """
    inspection = inspect_publish_authorization(
        input_path,
        direct_confirmation=direct_confirmation,
        run_id=run_id,
    )
    if not inspection["authorized"]:
        raise PublishAuthorizationError(
            f"Remote draft write blocked: {inspection['reason']}."
        )

    if inspection["mode"] == "direct":
        return {
            **inspection,
            "permission_consumed": False,
        }

    # Permission is intentionally one-shot.  Any failed remote attempt must be
    # explicitly authorized again instead of being retried silently by an agent.
    set_publish_permission(False, inspection["run_id"])
    return {
        **inspection,
        "mode": "run",
        "permission_consumed": True,
    }
