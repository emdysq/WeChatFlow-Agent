"""OpenAI-compatible text, JSON and vision model client."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .toolkit.config import load_config


class ModelConfigurationError(ValueError):
    """The writer provider is not configured for a real API call."""


class ModelResponseError(RuntimeError):
    """The provider returned an unusable response."""


_PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "reviewer_model": "deepseek-v4-pro",
        "vision_model": "deepseek-v4-flash-vision-exp",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "",
        "reviewer_model": "",
        "vision_model": "",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "",
        "reviewer_model": "",
        "vision_model": "",
    },
}


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key: str
    base_url: str
    model: str
    reviewer_model: str
    vision_model: str
    timeout_seconds: int = 180
    max_tokens: int = 6000
    temperature: float | None = None
    retries: int = 2

    @classmethod
    def from_config(cls, config: dict | None = None) -> "ModelSettings":
        cfg = load_config(force_reload=True) if config is None else config
        writer = cfg.get("writer", {}) or {}
        if not isinstance(writer, dict):
            raise ModelConfigurationError("config writer must be an object")
        provider = str(writer.get("provider") or "deepseek").strip().lower()
        defaults = _PROVIDER_DEFAULTS.get(provider, {})
        base_url = str(writer.get("base_url") or defaults.get("base_url") or "").rstrip("/")
        model = str(writer.get("model") or defaults.get("model") or "").strip()
        reviewer = str(writer.get("reviewer_model") or defaults.get("reviewer_model") or model).strip()
        vision = str(writer.get("vision_model") or defaults.get("vision_model") or "").strip()
        api_key = str(writer.get("api_key") or "").strip()
        if not api_key:
            raise ModelConfigurationError(
                "未配置写作模型 API Key；请在本机 config.yaml 的 writer.api_key 中填写，"
                "或设置 WEWRITE_WRITER_API_KEY"
            )
        if not base_url:
            raise ModelConfigurationError("非内置 provider 必须配置 writer.base_url")
        if not model:
            raise ModelConfigurationError("请配置 writer.model")
        try:
            timeout = int(writer.get("timeout_seconds", 180))
            max_tokens = int(writer.get("max_tokens", 6000))
            raw_temperature = writer.get("temperature")
            temperature = float(raw_temperature) if raw_temperature is not None else None
            retries = int(writer.get("retries", 2))
        except (TypeError, ValueError) as exc:
            raise ModelConfigurationError("writer 超时、token 或温度配置格式不正确") from exc
        if timeout <= 0 or max_tokens <= 0 or not 0 <= retries <= 5:
            raise ModelConfigurationError("writer 超时、max_tokens 必须大于 0，retries 必须在 0-5 之间")
        return cls(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            reviewer_model=reviewer or model,
            vision_model=vision,
            timeout_seconds=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            retries=retries,
        )


@dataclass(frozen=True)
class ModelResult:
    content: str
    model: str
    usage: dict = field(default_factory=dict)


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        value = value[first_newline + 1:] if first_newline >= 0 else ""
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


class OpenAICompatibleClient:
    """Small HTTP client shared by DeepSeek and compatible providers."""

    def __init__(
        self,
        settings: ModelSettings,
        transport: Callable[..., object] | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport or requests.post
        self.calls: list[dict] = []

    @property
    def endpoint(self) -> str:
        return self.settings.base_url + "/chat/completions"

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ModelResult:
        return self._request(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model or self.settings.model,
            json_mode=json_mode,
            max_tokens=max_tokens,
        )

    def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_path: str | Path,
        json_mode: bool = True,
    ) -> ModelResult:
        if not self.settings.vision_model:
            raise ModelConfigurationError("当前 writer 配置没有 vision_model")
        path = Path(image_path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            raise ValueError(f"不支持的图片格式: {path.suffix}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": "auto"},
            },
        ]
        return self._request(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            model=self.settings.vision_model,
            json_mode=json_mode,
            max_tokens=min(self.settings.max_tokens, 2500),
        )

    def parse_json(self, result: ModelResult) -> dict:
        content = _strip_fence(result.content).lstrip("\ufeff")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            # Some compatible providers prepend a short explanation even when
            # JSON mode is requested. Accept the first complete JSON object,
            # while still validating its structure below.
            start = content.find("{")
            if start < 0:
                raise ModelResponseError("模型没有返回有效 JSON") from exc
            try:
                value, _ = json.JSONDecoder().raw_decode(content[start:])
            except json.JSONDecodeError as nested:
                raise ModelResponseError("模型没有返回有效 JSON") from nested
        if not isinstance(value, dict):
            raise ModelResponseError("模型 JSON 顶层必须是对象")
        return value

    def _request(
        self,
        *,
        messages: list[dict],
        model: str,
        json_mode: bool,
        max_tokens: int | None,
    ) -> ModelResult:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or self.settings.max_tokens,
        }
        if self.settings.temperature is not None:
            payload["temperature"] = self.settings.temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            if self.settings.provider == "deepseek":
                payload["thinking"] = {"type": "disabled"}
        last_error: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                response = self._transport(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                break
            except Exception as exc:  # provider/network/schema errors share one CLI boundary
                last_error = exc
                retryable = isinstance(exc, requests.exceptions.RequestException)
                if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
                    retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt >= self.settings.retries:
                    raise ModelResponseError(f"模型调用失败: {type(exc).__name__}: {exc}") from exc
                time.sleep(min(2 ** attempt, 4))
        else:  # pragma: no cover - loop always raises or breaks
            raise ModelResponseError(f"模型调用失败: {last_error}")
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("模型返回了空内容")
        usage = data.get("usage") if isinstance(data, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        self.calls.append({"model": model, "usage": usage, "json_mode": json_mode})
        return ModelResult(content=content, model=model, usage=usage)
