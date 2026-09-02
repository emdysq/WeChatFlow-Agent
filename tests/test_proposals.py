import json

import pytest

from wewrite.proposals import (
    ProposalError,
    accept_proposal,
    create_proposal,
    reject_proposal,
    show_proposal,
)
from wewrite.runs import create_run, finish_run, load_run


def _proposal_run(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path))
    run = create_run(topic="可审阅改稿", review_mode="proposal")
    draft = tmp_path / run["artifacts"]["draft"]
    candidate = tmp_path / run["artifacts"]["proposal"]
    draft.write_text("# 标题\n\n旧内容。\n", encoding="utf-8")
    candidate.write_text("# 更准确的标题\n\n新内容，并补充边界。\n", encoding="utf-8")
    return run, draft, candidate


def test_create_and_accept_proposal_applies_candidate(tmp_path, monkeypatch):
    run, _draft, candidate = _proposal_run(tmp_path, monkeypatch)
    record = create_proposal(run["run_id"], summary="修正标题并补充边界")
    assert record["status"] == "pending"
    assert record["changes"]["additions"] == 2
    assert record["changes"]["deletions"] == 2
    assert "更准确的标题" in record["changes"]["unified_diff"]
    assert show_proposal(run["run_id"])["proposal_id"] == record["proposal_id"]
    assert load_run(run["run_id"])["proposal"]["status"] == "pending"

    accepted = accept_proposal(run["run_id"])
    article = tmp_path / run["artifacts"]["article"]
    assert accepted["status"] == "accepted"
    assert article.read_text(encoding="utf-8") == candidate.read_text(encoding="utf-8")


def test_reject_proposal_does_not_create_or_change_article(tmp_path, monkeypatch):
    run, _draft, _candidate = _proposal_run(tmp_path, monkeypatch)
    article = tmp_path / run["artifacts"]["article"]
    article.write_text("保留的现有成稿", encoding="utf-8")
    create_proposal(run["run_id"])
    rejected = reject_proposal(run["run_id"], reason="保留原结构")
    assert rejected["status"] == "rejected"
    assert rejected["decision_reason"] == "保留原结构"
    assert article.read_text(encoding="utf-8") == "保留的现有成稿"
    with pytest.raises(ProposalError, match="already rejected"):
        accept_proposal(run["run_id"])


def test_accept_uses_current_candidate_content(tmp_path, monkeypatch):
    run, _draft, candidate = _proposal_run(tmp_path, monkeypatch)
    create_proposal(run["run_id"])
    candidate.write_text("用户调整后的候选稿", encoding="utf-8")
    accepted = accept_proposal(run["run_id"])
    article = tmp_path / run["artifacts"]["article"]
    assert article.read_text(encoding="utf-8") == "用户调整后的候选稿"
    assert "用户调整后的候选稿" in accepted["changes"]["unified_diff"]


def test_proposal_mode_cannot_finish_without_acceptance(tmp_path, monkeypatch):
    run, _draft, candidate = _proposal_run(tmp_path, monkeypatch)
    article = tmp_path / run["artifacts"]["article"]
    article.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="accepted proposal"):
        finish_run(run_id=run["run_id"])

    create_proposal(run["run_id"])
    accept_proposal(run["run_id"])
    # A drafted article still needs the existing editorial pass contract.
    report = tmp_path / run["artifacts"]["review_report"]
    report.write_text(json.dumps({"decision": "pass", "publishable": True}), encoding="utf-8")
    finished = finish_run(
        {"editorial": {"decision": "pass", "publishable": True}},
        run["run_id"],
    )
    assert finished["status"] == "completed"
