import json

import pytest

from wewrite.publish_guard import PublishAuthorizationError, authorize_publish
from wewrite.runs import create_run, finish_run, load_run, set_publish_permission


def _completed_reviewed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path))
    run = create_run(topic="发布门禁测试")
    draft = tmp_path / run["artifacts"]["draft"]
    article = tmp_path / run["artifacts"]["article"]
    report = tmp_path / run["artifacts"]["review_report"]
    draft.write_text("初稿", encoding="utf-8")
    article.write_text("审稿通过的成稿", encoding="utf-8")
    report.write_text(
        json.dumps({"decision": "pass", "publishable": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    finish_run(
        {"editorial": {"decision": "pass", "publishable": True}},
        run["run_id"],
    )
    return run, article


def test_standalone_publish_requires_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path))
    article = tmp_path / "standalone.md"
    article.write_text("正文", encoding="utf-8")

    with pytest.raises(PublishAuthorizationError, match="no authorized current run"):
        authorize_publish(article)

    result = authorize_publish(article, direct_confirmation=True)
    assert result["mode"] == "direct"
    assert result["permission_consumed"] is False


def test_run_publish_requires_permission_and_consumes_it(tmp_path, monkeypatch):
    run, article = _completed_reviewed_run(tmp_path, monkeypatch)

    with pytest.raises(PublishAuthorizationError, match="permission is missing"):
        authorize_publish(article, run_id=run["run_id"])

    set_publish_permission(True, run["run_id"])
    result = authorize_publish(article, run_id=run["run_id"])

    assert result["run_id"] == run["run_id"]
    assert result["permission_consumed"] is True
    assert load_run(run["run_id"])["permissions"]["publish"] is False


def test_run_publish_rejects_unrelated_file(tmp_path, monkeypatch):
    run, _ = _completed_reviewed_run(tmp_path, monkeypatch)
    unrelated = tmp_path / "unrelated.md"
    unrelated.write_text("不是当前任务的文章", encoding="utf-8")
    set_publish_permission(True, run["run_id"])

    with pytest.raises(PublishAuthorizationError, match="not an article artifact"):
        authorize_publish(unrelated, run_id=run["run_id"])

    assert load_run(run["run_id"])["permissions"]["publish"] is True


def test_run_publish_requires_editorial_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path))
    run = create_run(topic="未审稿文章")
    article = tmp_path / run["artifacts"]["article"]
    article.write_text("正文", encoding="utf-8")
    finish_run(run_id=run["run_id"])
    set_publish_permission(True, run["run_id"])

    with pytest.raises(PublishAuthorizationError, match="editorial review"):
        authorize_publish(article, run_id=run["run_id"])
