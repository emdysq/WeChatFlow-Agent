import argparse
import json
from types import SimpleNamespace

from wewrite.runs import create_run, finish_run, load_run, set_publish_permission
from wewrite.toolkit import cli as toolkit_cli


def _args(**overrides):
    values = {
        "input": "",
        "theme": "professional-clean",
        "appid": None,
        "secret": None,
        "cover": None,
        "title": None,
        "author": None,
        "digest": None,
        "confirm_publish": False,
        "dry_run": False,
        "dry_run_output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _long_markdown(with_image: bool = False) -> str:
    body = "这是用于发布预检和集成测试的正文内容。" * 30
    image = "\n\n![流程图](figure.png)" if with_image else ""
    return f"# 发布链路测试\n\n{body}{image}\n"


def test_publish_dry_run_never_calls_network(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path / "state"))
    article = tmp_path / "article.md"
    cover = tmp_path / "cover.png"
    report_path = tmp_path / "dry-run.json"
    article.write_text(_long_markdown(), encoding="utf-8")
    cover.write_bytes(b"fake-cover")

    def network_forbidden(*args, **kwargs):
        raise AssertionError("dry-run attempted a network operation")

    monkeypatch.setattr(toolkit_cli, "get_access_token", network_forbidden)
    monkeypatch.setattr(toolkit_cli, "upload_image", network_forbidden)
    monkeypatch.setattr(toolkit_cli, "upload_thumb", network_forbidden)
    monkeypatch.setattr(toolkit_cli, "create_draft", network_forbidden)

    toolkit_cli.cmd_publish(
        _args(
            input=str(article),
            cover=str(cover),
            dry_run=True,
            dry_run_output=str(report_path),
        )
    )

    plan = json.loads(report_path.read_text(encoding="utf-8"))
    assert plan["network_request_performed"] is False
    assert plan["content_ready"] is True
    assert plan["remote_write_ready"] is False
    assert plan["authorization"]["authorized"] is False
    assert len(plan["html_sha256"]) == 64


def test_mock_publish_chain_uses_plan_and_consumes_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path))
    run = create_run(topic="Mock 发布链路")
    article = tmp_path / run["artifacts"]["article"]
    draft = tmp_path / run["artifacts"]["draft"]
    report = tmp_path / run["artifacts"]["review_report"]
    figure = article.parent / "figure.png"
    cover = article.parent / "cover.png"

    article.write_text(_long_markdown(with_image=True), encoding="utf-8")
    draft.write_text("初稿", encoding="utf-8")
    report.write_text(
        json.dumps({"decision": "pass", "publishable": True}),
        encoding="utf-8",
    )
    figure.write_bytes(b"fake-figure")
    cover.write_bytes(b"fake-cover")
    finish_run(
        {"editorial": {"decision": "pass", "publishable": True}},
        run["run_id"],
    )
    set_publish_permission(True, run["run_id"])

    events = []

    def fake_token(appid, secret):
        events.append(("token", appid, secret))
        return "mock-token"

    def fake_image(token, path):
        events.append(("image", token, path))
        return "https://mmbiz.qpic.cn/mock-figure"

    def fake_thumb(token, path):
        events.append(("thumb", token, path))
        return "mock-thumb-media-id"

    def fake_draft(**kwargs):
        events.append(("draft", kwargs))
        assert kwargs["access_token"] == "mock-token"
        assert kwargs["thumb_media_id"] == "mock-thumb-media-id"
        assert "https://mmbiz.qpic.cn/mock-figure" in kwargs["html"]
        assert "figure.png" not in kwargs["html"]
        return SimpleNamespace(media_id="mock-draft-media-id")

    monkeypatch.setattr(toolkit_cli, "get_access_token", fake_token)
    monkeypatch.setattr(toolkit_cli, "upload_image", fake_image)
    monkeypatch.setattr(toolkit_cli, "upload_thumb", fake_thumb)
    monkeypatch.setattr(toolkit_cli, "create_draft", fake_draft)

    toolkit_cli.cmd_publish(
        _args(
            input=str(article),
            cover=str(cover),
            appid="wx-mock",
            secret="secret-mock",
        )
    )

    assert [event[0] for event in events] == ["token", "image", "thumb", "draft"]
    assert load_run(run["run_id"])["permissions"]["publish"] is False
