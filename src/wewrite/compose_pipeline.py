"""One-command material-to-WeChat-draft composition pipeline."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

from .commands.content_eval import DIMENSIONS, build_report
from .commands.humanness_score import score_article
from .commands.validate_html import validate_html
from .material_ingest import MaterialPack, ingest_materials
from .model_client import ModelResponseError, OpenAICompatibleClient
from .runs import create_run, finish_run, mark_step, run_dir, update_run
from .sources import save_sources
from .toolkit.converter import WeChatConverter, make_paste_safe, preview_html
from .toolkit.theme import load_theme


class ComposeNeedsInput(RuntimeError):
    """The pipeline produced useful artifacts but cannot mark them publishable."""


_VISION_SYSTEM = """你是内容编辑的图片素材分析助手。只描述图片中明确可见的信息，不猜测人物身份、时间、地点、数据来源或图片外事件。输出 JSON 对象，包含 status、summary、visible_facts、caption、suggested_section。visible_facts 必须是字符串数组。"""

_PLAN_SYSTEM = """你是资深中文公众号策划编辑。只能依据用户素材包规划文章，不能补写未提供的经历、数字、引述或事实。输出 JSON 对象，必须包含 title、target_reader、purpose、core_argument、framework、target_words、sections、claims、image_plan。sections 是含 heading 和 purpose 的对象数组；claims 是含 id、claim、material_refs、kind 的对象数组，kind 只能是 user_provided、inference 或 opinion；image_plan 是含 asset_id、use、caption、after_section 的对象数组。没有材料支持的内容只能标为 inference/opinion。"""

_WRITE_SYSTEM = """你是资深中文公众号作者。严格依据任务书和用户素材写一篇可审阅的 Markdown 文章。不要编造亲历、身份、采访、朋友同事、数字、引述或来源；事实不足时缩小判断并明确边界。标题使用一级标题，正文使用二级标题，语言自然直接，避免空话、重复、口号和机械总结。图片只允许使用任务书中的资产编号，并以 {{IMAGE:IMG1}} 形式单独占一行。只输出正文，不要代码围栏和解释。"""

_REVIEW_SYSTEM = """你是严格的公众号责任编辑。对照用户素材和任务书审查文章，不允许把模型常识当成用户事实。输出 JSON 对象，必须包含 decision、dimensions、blockers、major_issues、notes、revision_instructions。decision 只能是 pass、revise、needs_input；dimensions 必须包含 accuracy、viewpoint、usefulness、voice、readability 五个 1-5 分整数；其余问题字段为字符串数组，revision_instructions 也是字符串数组。只有不存在阻断项、五维最低分不低于 3 且平均分不低于 4 时才能 pass。"""

_REVISE_SYSTEM = """你是中文公众号终稿编辑。依据编辑意见修改初稿，只解决明确问题，不增加用户素材之外的事实、数据、经历或引述。保留合法的 {{IMAGE:IMGn}} 占位符。输出完整 Markdown 成稿，不要代码围栏和解释。"""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, value: dict) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def _strip_markdown_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


def _normalize_plan(
    value: dict,
    *,
    topic: str,
    target_words: int,
    material_ids: set[str],
    image_ids: set[str],
) -> dict:
    required_strings = ("title", "target_reader", "purpose", "core_argument", "framework")
    for key in required_strings:
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ModelResponseError(f"任务书缺少有效字段: {key}")
    sections = value.get("sections")
    claims = value.get("claims")
    image_plan = value.get("image_plan", [])
    if not isinstance(sections, list) or not sections:
        raise ModelResponseError("任务书 sections 必须是非空数组")
    if not isinstance(claims, list):
        raise ModelResponseError("任务书 claims 必须是数组")
    if not isinstance(image_plan, list):
        raise ModelResponseError("任务书 image_plan 必须是数组")
    for section in sections:
        if not isinstance(section, dict) or not all(
            isinstance(section.get(key), str) and section[key].strip()
            for key in ("heading", "purpose")
        ):
            raise ModelResponseError("任务书每个 section 都需要 heading 和 purpose")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ModelResponseError("任务书每个 claim 都必须是对象")
        if not isinstance(claim.get("id"), str) or not isinstance(claim.get("claim"), str):
            raise ModelResponseError("任务书 claim 需要 id 和 claim")
        if claim.get("kind") not in {"user_provided", "inference", "opinion"}:
            raise ModelResponseError("任务书 claim.kind 不合法")
        refs = claim.get("material_refs", [])
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ModelResponseError("任务书 claim.material_refs 必须是字符串数组")
        unknown_refs = set(refs) - material_ids - image_ids
        if unknown_refs:
            raise ModelResponseError("任务书引用了不存在的素材编号: " + ", ".join(sorted(unknown_refs)))
    for image in image_plan:
        if not isinstance(image, dict) or image.get("asset_id") not in image_ids:
            raise ModelResponseError("任务书 image_plan 引用了不存在的图片")
    value["topic"] = topic
    value["target_words"] = target_words
    return value


def _normalize_assessment(value: dict, *, pass_number: int) -> dict:
    decision = value.get("decision")
    if decision not in {"pass", "revise", "needs_input"}:
        raise ModelResponseError("审稿 decision 必须是 pass、revise 或 needs_input")
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ModelResponseError("审稿 dimensions 必须是对象")
    normalized_scores = {}
    for name in DIMENSIONS:
        score = dimensions.get(name)
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ModelResponseError(f"审稿维度 {name} 必须是 1-5 分")
        normalized_scores[name] = float(score)
    normalized = {
        "decision": decision,
        "pass_number": pass_number,
        "dimensions": normalized_scores,
        "blockers": value.get("blockers", []),
        "major_issues": value.get("major_issues", []),
        "notes": value.get("notes", ""),
        "revision_instructions": value.get("revision_instructions", []),
    }
    for key in ("blockers", "major_issues", "revision_instructions"):
        if not isinstance(normalized[key], list) or not all(isinstance(x, str) for x in normalized[key]):
            raise ModelResponseError(f"审稿 {key} 必须是字符串数组")
    return normalized


def _vision_prompt(asset_id: str, name: str) -> str:
    return (
        "请分析这张用户提供的公众号素材图片，并输出 json。"
        f"资产编号：{asset_id}；文件名：{name}。"
        "如果图片无法辨认，把 status 设为 unusable，不要猜测。"
    )


def _analyze_images(pack: MaterialPack, client: OpenAICompatibleClient, directory: Path) -> None:
    for image in pack.images:
        if not client.settings.vision_model:
            image.analysis = {"status": "unparsed", "reason": "vision_model 未配置"}
            continue
        try:
            result = client.vision(
                system=_VISION_SYSTEM,
                prompt=_vision_prompt(image.asset_id, image.name),
                image_path=directory / image.relative_path,
            )
            analysis = client.parse_json(result)
            facts = analysis.get("visible_facts", [])
            if not isinstance(facts, list):
                raise ModelResponseError("图片 visible_facts 必须是数组")
            image.analysis = {
                "status": str(analysis.get("status") or "ok"),
                "summary": str(analysis.get("summary") or ""),
                "visible_facts": [str(item) for item in facts],
                "caption": str(analysis.get("caption") or ""),
                "suggested_section": str(analysis.get("suggested_section") or ""),
            }
        except (OSError, ValueError, ModelResponseError) as exc:
            image.analysis = {"status": "unparsed", "reason": str(exc)}


def _save_user_sources(pack: MaterialPack, run_id: str) -> None:
    today = date.today().isoformat()
    entries = []
    for item in pack.texts:
        entries.append({
            "id": item.material_id,
            "title": item.name,
            "publisher": "用户提供",
            "url": "user-provided://material",
            "published_at": None,
            "accessed_at": today,
            "claim": "本次写作使用的用户文字材料",
            "status": "user_provided",
        })
    for image in pack.images:
        entries.append({
            "id": image.asset_id,
            "title": image.name,
            "publisher": "用户提供",
            "url": "user-provided://image",
            "published_at": None,
            "accessed_at": today,
            "claim": "本次写作使用的用户图片材料",
            "status": "user_provided",
        })
    save_sources({"sources": entries}, run_id)


def _apply_image_placeholders(article: str, pack: MaterialPack) -> tuple[str, list[str]]:
    used: list[str] = []
    for image in pack.images:
        token = "{{IMAGE:" + image.asset_id + "}}"
        if token not in article:
            continue
        caption = str((image.analysis or {}).get("caption") or image.name).replace("[", "").replace("]", "")
        article = article.replace(token, f"![{caption}]({image.relative_path})")
        used.append(image.asset_id)
    article = re.sub(r"\{\{IMAGE:[A-Za-z0-9_-]+\}\}", "", article)
    return article, used


def _review(
    client: OpenAICompatibleClient,
    *,
    article: str,
    brief: dict,
    materials: str,
    pass_number: int,
) -> dict:
    prompt = (
        "请按要求输出 json 审稿结果。\n\n"
        "## 任务书\n" + yaml.safe_dump(brief, allow_unicode=True, sort_keys=False) +
        "\n## 用户素材\n" + materials +
        "\n## 待审文章\n" + article
    )
    result = client.complete(
        system=_REVIEW_SYSTEM,
        user=prompt,
        model=client.settings.reviewer_model,
        json_mode=True,
        max_tokens=min(client.settings.max_tokens, 3500),
    )
    return _normalize_assessment(client.parse_json(result), pass_number=pass_number)


def compose_article(
    *,
    client: OpenAICompatibleClient,
    topic: str,
    material_paths: list[str],
    image_paths: list[str],
    notes: str = "",
    theme_name: str = "professional-clean",
    target_words: int = 1800,
    review_passes: int = 2,
) -> dict:
    """Run the complete local composition workflow and return an audit summary."""
    if not topic.strip():
        raise ValueError("topic 不能为空")
    if not 500 <= target_words <= 5000:
        raise ValueError("target_words 必须在 500-5000 之间")
    if review_passes not in {1, 2}:
        raise ValueError("review_passes 只能是 1 或 2")

    state = create_run(topic=topic.strip(), mode="complete", visual_mode="none", review_mode="auto")
    run_id = state["run_id"]
    directory = run_dir(run_id)
    current_step = "ingest"
    report = {
        "version": 1,
        "run_id": run_id,
        "status": "in_progress",
        "models": {
            "provider": client.settings.provider,
            "writer": client.settings.model,
            "reviewer": client.settings.reviewer_model,
            "vision": client.settings.vision_model or None,
        },
    }

    try:
        mark_step(current_step, "in_progress", run_id)
        pack = ingest_materials(
            material_paths=material_paths,
            image_paths=image_paths,
            run_directory=directory,
            notes=notes,
        )
        _analyze_images(pack, client, directory)
        materials_text = pack.as_prompt()
        _write_text(directory / "materials.md", materials_text)
        _save_user_sources(pack, run_id)
        report["materials"] = {
            "text_count": len(pack.texts),
            "image_count": len(pack.images),
            "skipped": pack.skipped,
        }
        mark_step(current_step, "completed", run_id)

        current_step = "plan"
        mark_step(current_step, "in_progress", run_id)
        plan_result = client.complete(
            system=_PLAN_SYSTEM,
            user=(
                "请为下面主题和素材制定写作任务书并输出 json。"
                f"\n主题：{topic}\n目标字数：{target_words}\n\n{materials_text}"
            ),
            json_mode=True,
            max_tokens=min(client.settings.max_tokens, 4000),
        )
        brief = _normalize_plan(
            client.parse_json(plan_result),
            topic=topic,
            target_words=target_words,
            material_ids={item.material_id for item in pack.texts},
            image_ids={item.asset_id for item in pack.images},
        )
        _write_text(directory / "brief.yaml", yaml.safe_dump(brief, allow_unicode=True, sort_keys=False))
        _write_text(
            directory / "claims.yaml",
            yaml.safe_dump({"version": 1, "claims": brief["claims"]}, allow_unicode=True, sort_keys=False),
        )
        mark_step(current_step, "completed", run_id)

        current_step = "write"
        mark_step(current_step, "in_progress", run_id)
        writing_input = (
            "## 任务书\n" + yaml.safe_dump(brief, allow_unicode=True, sort_keys=False) +
            "\n## 用户素材\n" + materials_text
        )
        draft_result = client.complete(system=_WRITE_SYSTEM, user=writing_input)
        draft = _strip_markdown_fence(draft_result.content)
        if not draft:
            raise ModelResponseError("写作模型没有生成正文")
        if not re.search(r"^#\s+\S", draft, re.MULTILINE):
            draft = f"# {brief['title']}\n\n{draft}"
        _write_text(directory / "draft.md", draft)
        mark_step(current_step, "completed", run_id)

        current_step = "review"
        mark_step(current_step, "in_progress", run_id)
        assessment = _review(
            client,
            article=draft,
            brief=brief,
            materials=materials_text,
            pass_number=1,
        )
        final_article = draft
        if assessment["decision"] == "revise" and review_passes == 2:
            revision_prompt = (
                "## 任务书\n" + yaml.safe_dump(brief, allow_unicode=True, sort_keys=False) +
                "\n## 修改要求\n" + yaml.safe_dump(assessment["revision_instructions"], allow_unicode=True) +
                "\n## 初稿\n" + draft
            )
            revised = client.complete(
                system=_REVISE_SYSTEM,
                user=revision_prompt,
                model=client.settings.reviewer_model,
            )
            final_article = _strip_markdown_fence(revised.content)
            assessment = _review(
                client,
                article=final_article,
                brief=brief,
                materials=materials_text,
                pass_number=2,
            )

        editorial_report = build_report(draft, final_article, assessment)
        editorial_report["revision_instructions"] = assessment["revision_instructions"]
        _write_json(directory / "review-report.json", editorial_report)
        if not editorial_report["publishable"]:
            _write_text(directory / "article.md", final_article)
            report["status"] = "needs_input"
            report["review"] = editorial_report
            report["calls"] = client.calls
            _write_json(directory / "compose-report.json", report)
            raise ComposeNeedsInput("自动审稿未通过，已保留文章和问题清单供人工处理")
        mark_step(current_step, "completed", run_id)

        final_article, used_images = _apply_image_placeholders(final_article, pack)
        _write_text(directory / "article.md", final_article)

        current_step = "render"
        mark_step(current_step, "in_progress", run_id)
        theme = load_theme(theme_name)
        converted = WeChatConverter(theme=theme).convert(final_article)
        issues = validate_html(converted.html)
        errors = [item for item in issues if item["level"] == "ERROR"]
        if errors:
            raise ValueError("微信 HTML 兼容性校验未通过")
        html = preview_html(make_paste_safe(converted.html), theme)
        _write_text(directory / "preview.html", html)
        quality = score_article(final_article)
        mark_step(current_step, "completed", run_id)

        update_run(
            {
                "editorial": {
                    "decision": editorial_report["decision"],
                    "publishable": editorial_report["publishable"],
                },
                "seo": {"title": converted.title or brief["title"], "quality_score": quality["quality_score"]},
                "word_count": len(re.sub(r"\s+", "", final_article)),
                "provenance": {"user_materials": len(pack.texts) + len(pack.images)},
                "compose": {"theme": theme_name, "used_images": used_images},
            },
            run_id,
        )
        finish_run(run_id=run_id)
        report.update({
            "status": "completed",
            "article": str(directory / "article.md"),
            "preview": str(directory / "preview.html"),
            "quality_score": quality["quality_score"],
            "used_images": used_images,
            "review": editorial_report,
            "validation": {"errors": 0, "warnings": len(issues)},
            "calls": client.calls,
        })
        _write_json(directory / "compose-report.json", report)
        return report
    except Exception as exc:
        if report.get("status") != "needs_input":
            report["status"] = "failed"
            report["error"] = str(exc)
            report["calls"] = client.calls
            _write_json(directory / "compose-report.json", report)
        try:
            mark_step(current_step, "failed", run_id, str(exc))
        except (OSError, ValueError):
            pass
        raise
