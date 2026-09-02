"""Simple reviewable article revisions for a WeWrite run."""

from __future__ import annotations

import difflib
import json
import os
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from .paths import home
from .runs import load_run, update_run


class ProposalError(ValueError):
    """A proposal is invalid, stale, or cannot transition state."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_required(path: Path, label: str) -> str:
    if not path.is_file():
        raise ProposalError(f"{label} file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ProposalError(f"{label} file is empty: {path}")
    return text


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.stem, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _artifact_path(state: dict, name: str) -> Path:
    relative = (state.get("artifacts") or {}).get(name)
    if not relative:
        raise ProposalError(f"Run has no {name} artifact")
    candidate = (home() / relative).resolve()
    run_root = (home() / "runs" / state["run_id"]).resolve()
    if candidate != run_root and run_root not in candidate.parents:
        raise ProposalError(f"Artifact escapes run directory: {name}")
    return candidate


def _record_path(state: dict) -> Path:
    return _artifact_path(state, "proposal_record")


def _load_record(state: dict) -> dict:
    path = _record_path(state)
    if not path.is_file():
        raise ProposalError("No proposal exists for this run")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProposalError(f"Proposal record is invalid JSON: {path}") from exc
    if record.get("run_id") != state["run_id"]:
        raise ProposalError("Proposal record belongs to another run")
    return record


def _save_record(state: dict, record: dict) -> None:
    _atomic_write(_record_path(state), json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def _build_diff(base: str, candidate: str) -> tuple[str, int, int]:
    lines = list(difflib.unified_diff(
        base.splitlines(),
        candidate.splitlines(),
        fromfile="draft.md",
        tofile="proposal.md",
        lineterm="",
    ))
    additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return "\n".join(lines) + ("\n" if lines else ""), additions, deletions


def create_proposal(
    run_id: str | None = None,
    *,
    summary: str = "",
    replace: bool = False,
) -> dict:
    state = load_run(run_id)
    if state.get("status") == "completed":
        raise ProposalError("Completed runs are immutable; start a new run to revise the article")
    record_path = _record_path(state)
    if record_path.exists() and not replace:
        existing = _load_record(state)
        if existing.get("status") == "pending":
            raise ProposalError("A pending proposal already exists; decide it or use --replace")

    base_path = _artifact_path(state, "draft")
    candidate_path = _artifact_path(state, "proposal")
    target_path = _artifact_path(state, "article")
    base = _read_required(base_path, "Draft")
    candidate = _read_required(candidate_path, "Candidate")
    if base == candidate:
        raise ProposalError("Candidate is identical to the draft")
    unified_diff, additions, deletions = _build_diff(base, candidate)
    record = {
        "version": 1,
        "proposal_id": secrets.token_hex(8),
        "run_id": state["run_id"],
        "status": "pending",
        "created_at": _now(),
        "decided_at": None,
        "decision_reason": "",
        "summary": summary,
        "files": {
            "base": str(base_path.relative_to(home())),
            "candidate": str(candidate_path.relative_to(home())),
            "target": str(target_path.relative_to(home())),
        },
        "changes": {
            "additions": additions,
            "deletions": deletions,
            "unified_diff": unified_diff,
        },
    }
    _save_record(state, record)
    update_run({"proposal": {
        "id": record["proposal_id"],
        "status": "pending",
        "summary": summary,
        "additions": additions,
        "deletions": deletions,
    }}, state["run_id"])
    return record


def show_proposal(run_id: str | None = None) -> dict:
    return _load_record(load_run(run_id))


def _pending_candidate(record: dict) -> tuple[str, Path]:
    if record.get("status") != "pending":
        raise ProposalError(f"Proposal is already {record.get('status', 'invalid')}")
    candidate_path = home() / record["files"]["candidate"]
    target_path = home() / record["files"]["target"]
    candidate = _read_required(candidate_path, "Candidate")
    return candidate, target_path


def accept_proposal(run_id: str | None = None) -> dict:
    state = load_run(run_id)
    if state.get("status") == "completed":
        raise ProposalError("Completed runs are immutable")
    record = _load_record(state)
    candidate, target_path = _pending_candidate(record)
    base_path = home() / record["files"]["base"]
    base = _read_required(base_path, "Draft")
    unified_diff, additions, deletions = _build_diff(base, candidate)
    record["changes"] = {
        "additions": additions,
        "deletions": deletions,
        "unified_diff": unified_diff,
    }
    _atomic_write(target_path, candidate)
    record["status"] = "accepted"
    record["decided_at"] = _now()
    _save_record(state, record)
    update_run({"proposal": {
        "id": record["proposal_id"],
        "status": "accepted",
        "decided_at": record["decided_at"],
    }}, state["run_id"])
    return record


def reject_proposal(run_id: str | None = None, *, reason: str = "") -> dict:
    state = load_run(run_id)
    if state.get("status") == "completed":
        raise ProposalError("Completed runs are immutable")
    record = _load_record(state)
    if record.get("status") != "pending":
        raise ProposalError(f"Proposal is already {record.get('status', 'invalid')}")
    record["status"] = "rejected"
    record["decided_at"] = _now()
    record["decision_reason"] = reason
    _save_record(state, record)
    update_run({"proposal": {
        "id": record["proposal_id"],
        "status": "rejected",
        "decided_at": record["decided_at"],
        "reason": reason,
    }}, state["run_id"])
    return record
