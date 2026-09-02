"""Build a deterministic, serializable preflight plan for WeChat publishing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .commands.validate_html import validate_html
from .toolkit.publisher import html_to_plaintext


def resolve_article_images(input_path: str | Path, image_sources: list[str]) -> list[dict]:
    """Resolve image references exactly as the live publisher will use them."""
    markdown_dir = Path(input_path).resolve().parent
    resolved = []
    for source in image_sources:
        if source.startswith(("http://", "https://")):
            resolved.append(
                {
                    "source": source,
                    "kind": "remote",
                    "resolved_path": None,
                    "exists": True,
                    "action": "keep_remote_url",
                }
            )
            continue

        candidate = Path(source)
        if not candidate.is_absolute() and not candidate.exists():
            candidate = markdown_dir / source
        candidate = candidate.resolve()
        exists = candidate.is_file()
        resolved.append(
            {
                "source": source,
                "kind": "local" if exists else "missing",
                "resolved_path": str(candidate),
                "exists": exists,
                "action": "upload_to_wechat" if exists else "block",
            }
        )
    return resolved


def build_publish_plan(
    *,
    input_path: str | Path,
    title: str,
    digest: str,
    theme: str,
    html: str,
    image_sources: list[str],
    cover_path: str | Path | None,
    authorization: dict,
) -> dict:
    """Return local readiness, blockers, and an auditable HTML fingerprint."""
    article_path = Path(input_path).resolve()
    cover = Path(cover_path).resolve() if cover_path else None
    cover_exists = bool(cover and cover.is_file())
    images = resolve_article_images(article_path, image_sources)
    issues = validate_html(html)
    errors = [issue for issue in issues if issue["level"] == "ERROR"]
    warnings = [issue for issue in issues if issue["level"] == "WARN"]
    text_length = len(html_to_plaintext(html))

    blockers = []
    if not title.strip():
        blockers.append("article title is empty")
    if len(digest.encode("utf-8")) > 120:
        blockers.append("digest exceeds 120 UTF-8 bytes")
    if text_length < 200 or text_length > 20_000:
        blockers.append(f"article text length {text_length} is outside 200-20000")
    if not cover_exists:
        blockers.append("an existing cover image is required")
    missing_images = [item["source"] for item in images if not item["exists"]]
    if missing_images:
        blockers.append("missing local article images: " + ", ".join(missing_images))
    if len(images) > 10:
        blockers.append(f"article contains {len(images)} images; maximum is 10")
    if errors:
        blockers.append(f"HTML compatibility validation has {len(errors)} error(s)")

    content_ready = not blockers
    return {
        "version": 1,
        "operation": "wechat_draft_add",
        "network_request_performed": False,
        "input": str(article_path),
        "title": title,
        "digest": digest,
        "digest_utf8_bytes": len(digest.encode("utf-8")),
        "theme": theme,
        "text_length": text_length,
        "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "cover": {
            "path": str(cover) if cover else None,
            "exists": cover_exists,
            "action": "upload_as_thumb" if cover_exists else "block",
        },
        "images": images,
        "compatibility": {
            "errors": errors,
            "warnings": warnings,
        },
        "authorization": authorization,
        "blockers": blockers,
        "content_ready": content_ready,
        "remote_write_ready": content_ready and authorization.get("authorized") is True,
    }
