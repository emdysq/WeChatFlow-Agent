import json
from pathlib import Path

import pytest
import requests
import yaml
from PIL import Image

from wewrite.compose_pipeline import ComposeNeedsInput, compose_article
from wewrite.material_ingest import ingest_materials
from wewrite.model_client import ModelSettings, OpenAICompatibleClient
from wewrite.runs import load_run


class FakeResponse:
    def __init__(self, content, model="fake-model", usage=None):
        self.payload = {
            "choices": [{"message": {"content": content}}],
            "model": model,
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20},
        }

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _settings(vision=True):
    return ModelSettings(
        provider="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reviewer_model="deepseek-v4-pro",
        vision_model="deepseek-v4-flash-vision-exp" if vision else "",
        timeout_seconds=30,
        max_tokens=6000,
    )


def _plan(include_image=True):
    value = {
        "title": "AI Agent 怎么真正进入工作",
        "target_reader": "希望改进内容流程的运营人员",
        "purpose": "给出可执行判断",
        "core_argument": "先把人工确认点设计清楚，再谈自动化",
        "framework": "问题—方法—边界",
        "target_words": 1200,
        "sections": [
            {"heading": "真正的问题", "purpose": "说明工作流断点"},
            {"heading": "落地方法", "purpose": "给出步骤"},
        ],
        "claims": [
            {"id": "C1", "claim": "人工确认点不能省略", "material_refs": ["M1 用户材料"], "kind": "inference"}
        ],
        "image_plan": [],
    }
    if include_image:
        value["image_plan"] = [
            {"asset_id": "[IMG1] 流程图", "use": True, "caption": "流程示意", "after_section": "落地方法"}
        ]
    return value


def _assessment(decision="pass", instructions=None):
    return {
        "decision": decision,
        "dimensions": {
            "accuracy": 4,
            "viewpoint": 4,
            "usefulness": 4,
            "voice": 4,
            "readability": 4,
        },
        "blockers": [],
        "major_issues": [] if decision == "pass" else ["结论还不够具体"],
        "notes": "可以发布" if decision == "pass" else "需要修改",
        "revision_instructions": instructions or [],
    }


def _transport(contents, captured):
    queue = list(contents)

    def send(url, **kwargs):
        captured.append({"url": url, **kwargs})
        return FakeResponse(queue.pop(0))

    return send


def test_deepseek_settings_have_current_official_defaults():
    settings = ModelSettings.from_config({"writer": {"api_key": "local-key"}})
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-flash"
    assert settings.reviewer_model == "deepseek-v4-pro"
    assert settings.vision_model == "deepseek-v4-flash-vision-exp"


def test_material_ingest_allows_topic_only_workflow(tmp_path):
    pack = ingest_materials(
        material_paths=[],
        image_paths=[],
        run_directory=tmp_path / "run",
    )
    assert pack.texts == []
    assert pack.images == []
    assert "用户素材包" in pack.as_prompt()


def test_material_ingest_reads_docx_html_and_copies_images(tmp_path):
    from docx import Document

    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "notes.html").write_text("<h1>标题</h1><p>一段事实。</p>", encoding="utf-8")
    doc = Document()
    doc.add_paragraph("访谈记录")
    doc.save(materials / "interview.docx")
    Image.new("RGB", (20, 10), "blue").save(materials / "chart.png")

    pack = ingest_materials(
        material_paths=[materials],
        image_paths=[],
        run_directory=tmp_path / "run",
    )

    assert [item.name for item in pack.texts] == ["interview.docx", "notes.html"]
    assert "访谈记录" in pack.texts[0].content
    assert "一段事实" in pack.texts[1].content
    assert pack.images[0].width == 20
    assert (tmp_path / "run" / pack.images[0].relative_path).is_file()


def test_model_client_builds_json_and_vision_requests(tmp_path):
    image_path = tmp_path / "input.png"
    Image.new("RGB", (4, 4), "red").save(image_path)
    captured = []
    client = OpenAICompatibleClient(
        _settings(),
        transport=_transport([json.dumps({"ok": True}), json.dumps({"summary": "红色"})], captured),
    )

    result = client.complete(system="输出 json", user="test", json_mode=True)
    vision = client.vision(system="输出 json", prompt="看图", image_path=image_path)

    assert client.parse_json(result) == {"ok": True}
    assert client.parse_json(vision)["summary"] == "红色"
    assert captured[0]["json"]["response_format"] == {"type": "json_object"}
    assert captured[0]["json"]["thinking"] == {"type": "disabled"}
    blocks = captured[1]["json"]["messages"][1]["content"]
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured[1]["json"]["model"] == "deepseek-v4-flash-vision-exp"


def test_model_client_accepts_json_after_provider_explanation():
    client = OpenAICompatibleClient(_settings(vision=False), transport=lambda *args, **kwargs: None)
    result = type("Result", (), {"content": "下面是结果：\n{\"ok\": true}\n完成。"})()
    assert client.parse_json(result) == {"ok": True}


def test_model_client_retries_transient_network_failure():
    attempts = []

    def flaky(url, **kwargs):
        attempts.append(url)
        if len(attempts) == 1:
            raise requests.exceptions.ChunkedEncodingError("connection ended")
        return FakeResponse("完成")

    client = OpenAICompatibleClient(_settings(vision=False), transport=flaky)
    assert client.complete(system="system", user="user").content == "完成"
    assert len(attempts) == 2


def test_deepseek_disables_thinking_for_plain_text_requests():
    captured = []
    client = OpenAICompatibleClient(
        _settings(vision=False),
        transport=_transport(["正文"], captured),
    )

    client.complete(system="system", user="user")

    assert captured[0]["json"]["thinking"] == {"type": "disabled"}


def test_compose_generates_reviewed_article_preview_and_state(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path / "home"))
    material = tmp_path / "material.md"
    material.write_text("人工确认点可以减少错误写入。", encoding="utf-8")
    image_path = tmp_path / "workflow.png"
    Image.new("RGB", (24, 12), "green").save(image_path)
    captured = []
    responses = [
        json.dumps({
            "status": "ok",
            "summary": "绿色流程示意图",
            "visible_facts": ["图中存在流程箭头"],
            "caption": "内容工作流示意",
            "suggested_section": "落地方法",
        }, ensure_ascii=False),
        json.dumps(_plan(), ensure_ascii=False),
        "# AI Agent 怎么真正进入工作\n\n## 真正的问题\n\n自动化需要确认点。\n\n## 落地方法\n\n{{IMAGE:IMG1}}\n\n先检查，再执行。",
        json.dumps(_assessment(), ensure_ascii=False),
    ]
    client = OpenAICompatibleClient(_settings(), transport=_transport(responses, captured))

    report = compose_article(
        client=client,
        topic="AI Agent 怎么真正进入工作",
        material_paths=[str(material)],
        image_paths=[str(image_path)],
        target_words=1200,
    )

    state = load_run(report["run_id"])
    run_directory = Path(report["article"]).parent
    article = Path(report["article"]).read_text(encoding="utf-8")
    assert state["status"] == "completed"
    assert state["editorial"]["publishable"] is True
    assert "![内容工作流示意](assets/01-workflow.png)" in article
    assert Path(report["preview"]).is_file()
    assert (run_directory / "materials.md").is_file()
    assert (run_directory / "compose-report.json").is_file()
    assert len(captured) == 4


def test_compose_revises_once_then_rechecks(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path / "home"))
    material = tmp_path / "notes.txt"
    material.write_text("关键材料。", encoding="utf-8")
    captured = []
    responses = [
        json.dumps(_plan(include_image=False), ensure_ascii=False),
        "# 初稿标题\n\n## 真正的问题\n\n含糊结论。",
        json.dumps(_assessment("revise", ["把结论写具体"]), ensure_ascii=False),
        "# 修改后的标题\n\n## 真正的问题\n\n先设置人工确认点，再执行远程写入。",
        json.dumps(_assessment(), ensure_ascii=False),
    ]
    client = OpenAICompatibleClient(_settings(vision=False), transport=_transport(responses, captured))

    report = compose_article(
        client=client,
        topic="修改流程",
        material_paths=[str(material)],
        image_paths=[],
        target_words=1000,
    )

    assert report["review"]["pass_number"] == 2
    assert report["review"]["edit_ratio"] > 0
    assert "设置人工确认点" in Path(report["article"]).read_text(encoding="utf-8")
    assert len(captured) == 5


def test_compose_needs_input_preserves_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("WEWRITE_HOME", str(tmp_path / "home"))
    material = tmp_path / "notes.txt"
    material.write_text("材料不足。", encoding="utf-8")
    assessment = _assessment("needs_input")
    assessment["blockers"] = ["缺少关键数据"]
    captured = []
    client = OpenAICompatibleClient(
        _settings(vision=False),
        transport=_transport([
            json.dumps(_plan(include_image=False), ensure_ascii=False),
            "# 待补充文章\n\n## 问题\n\n目前材料不足。",
            json.dumps(assessment, ensure_ascii=False),
        ], captured),
    )

    with pytest.raises(ComposeNeedsInput):
        compose_article(
            client=client,
            topic="材料不足测试",
            material_paths=[str(material)],
            image_paths=[],
        )

    state = load_run()
    directory = tmp_path / "home" / "runs" / state["run_id"]
    assert state["status"] == "failed"
    assert (directory / "article.md").is_file()
    report = json.loads((directory / "compose-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_input"
    assert report["review"]["publishable"] is False
