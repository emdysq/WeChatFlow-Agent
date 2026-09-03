"""CLI for topic + materials + images → reviewed WeChat article."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from ..compose_pipeline import ComposeNeedsInput, compose_article
from ..model_client import (
    ModelConfigurationError,
    ModelResponseError,
    ModelSettings,
    OpenAICompatibleClient,
)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="根据主题、用户材料和图片自动生成经审稿的公众号成稿与预览"
    )
    parser.add_argument("--topic", required=True, help="文章主题")
    parser.add_argument(
        "--material",
        action="append",
        default=[],
        help="素材文件或目录，可重复传入",
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="额外图片文件或目录，可重复传入",
    )
    parser.add_argument("--notes", default="", help="直接补充的文字材料")
    parser.add_argument("--theme", default="professional-clean", help="微信排版主题")
    parser.add_argument("--target-words", type=int, default=1800, help="目标字数，500-5000")
    parser.add_argument("--review-passes", type=int, choices=[1, 2], default=2)
    parser.add_argument("--model", help="临时覆盖写作模型")
    parser.add_argument("--reviewer-model", help="临时覆盖审稿模型")
    parser.add_argument("--vision-model", help="临时覆盖视觉模型")
    parser.add_argument("--json", action="store_true", help="输出完整执行报告 JSON")
    args = parser.parse_args(argv)

    try:
        settings = ModelSettings.from_config()
        settings = replace(
            settings,
            model=args.model or settings.model,
            reviewer_model=args.reviewer_model or settings.reviewer_model,
            vision_model=args.vision_model or settings.vision_model,
        )
        report = compose_article(
            client=OpenAICompatibleClient(settings),
            topic=args.topic,
            material_paths=args.material,
            image_paths=args.image,
            notes=args.notes,
            theme_name=args.theme,
            target_words=args.target_words,
            review_passes=args.review_passes,
        )
    except ComposeNeedsInput as exc:
        print(f"NEEDS_INPUT: {exc}", file=sys.stderr)
        raise SystemExit(5)
    except (FileNotFoundError, OSError, ValueError, ModelConfigurationError, ModelResponseError) as exc:
        print(f"COMPOSE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(4)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("一键出稿完成")
        print(f"Run: {report['run_id']}")
        print(f"Article: {report['article']}")
        print(f"Preview: {report['preview']}")
        print(f"Quality score: {report['quality_score']}")


if __name__ == "__main__":
    main()
