"""Provider model discovery for Agent City.

Discovery only: this module never calls inference and never treats a catalogue
as proof that a model is free.  Sources are the providers' documented model
endpoints: Gemini (https://ai.google.dev/api/models), Groq
(https://console.groq.com/docs/models), Cerebras
(https://inference-docs.cerebras.ai/api-reference/models/public-models),
Mistral (https://docs.mistral.ai/api/endpoint/models), and SiliconFlow
(https://docs.siliconflow.cn/docs/api/chat-completions-post).
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable, Mapping
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_JSON = 4 * 1024 * 1024
TIMEOUT = 15
MAX_GEMINI_PAGES = 5
MAX_MODELS = 2000

_CHINESE = {
    "qwen", "deepseek", "z-ai", "zai", "thudm", "moonshotai", "minimax",
    "minimaxai", "stepfun", "stepfun-ai", "baidu", "tencent", "bytedance",
    "bytedance-seed", "xiaomi", "meituan", "alibaba", "alibaba-cloud",
    "01-ai", "internlm", "dots-studio", "glm", "zhipuai",
}

SOURCES: dict[str, dict[str, Any]] = {
    "huggingface": {
        "name": "Hugging Face", "url": "https://router.huggingface.co/v1/models",
        "docs": "https://huggingface.co/docs/inference-providers/hub-api",
        "keyUrl": "https://huggingface.co/settings/tokens", "auth": "bearer", "accountCatalog": False,
        "terms": "Публичный каталог Inference Providers. Для вызова нужен HF token; бесплатные кредиты зависят от аккаунта.",
    },
    "gemini": {
        "name": "Google Gemini", "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "docs": "https://ai.google.dev/api/models", "keyUrl": "https://aistudio.google.com/apikey",
        "auth": "google", "accountCatalog": True,
        "terms": "Каталог доступен с API-ключом; бесплатность квоты не подтверждается каталогом.",
    },
    "groq": {
        "name": "Groq", "url": "https://api.groq.com/openai/v1/models",
        "docs": "https://console.groq.com/docs/models", "keyUrl": "https://console.groq.com/keys",
        "auth": "bearer", "accountCatalog": True,
        "terms": "Free quota и платный тариф разделены; каталог не доказывает нулевую цену.",
    },
    "cerebras": {
        "name": "Cerebras", "url": "https://api.cerebras.ai/public/v1/models",
        "docs": "https://inference-docs.cerebras.ai/api-reference/models/public-models",
        "keyUrl": "https://cloud.cerebras.ai/", "auth": "bearer", "accountCatalog": False,
        "terms": "Публичный каталог без ключа; free-tier доступ и тариф модели проверяются отдельно.",
    },
    "mistral": {
        "name": "Mistral AI", "url": "https://api.mistral.ai/v1/models",
        "docs": "https://docs.mistral.ai/api/endpoint/models", "keyUrl": "https://console.mistral.ai/",
        "auth": "bearer", "accountCatalog": True,
        "terms": "Free mode ограничен квотой; подключение pay-as-you-go может сделать вызовы платными.",
    },
    "siliconflow": {
        "name": "SiliconFlow", "url": "https://api.siliconflow.cn/v1/models?type=text&sub_type=chat",
        "docs": "https://docs.siliconflow.cn/docs/api/chat-completions-post",
        "keyUrl": "https://cloud.siliconflow.cn/account/ak", "auth": "bearer", "accountCatalog": True,
        "terms": "Модели и квоты меняются; цены нужно сверять в Model Library, каталог не доказывает free.",
    },
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("redirect disabled")


def _key(key_reader: Any, provider: str) -> str | None:
    if key_reader is None:
        return None
    value = key_reader(provider) if callable(key_reader) else key_reader.get(provider)
    return value if isinstance(value, str) and value else None


def _with_query(url: str, **updates: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(updates)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _read_json(url: str, headers: Mapping[str, str], limit: int) -> tuple[bytes, Any]:
    request = Request(url, headers=dict(headers), method="GET")
    with build_opener(_NoRedirect()).open(request, timeout=TIMEOUT) as response:
        if getattr(response, "status", 200) != 200:
            raise ValueError(f"catalog HTTP {response.status}")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("catalog response too large")
    return raw, json.loads(raw)


def fetch(provider: str, key_reader: Callable[[str], str | None] | Mapping[str, str] | None) -> dict[str, Any]:
    """Fetch one bounded JSON catalogue using only the supplied credential reader."""
    source = SOURCES[provider]
    headers = {"Accept": "application/json"}
    if provider == 'huggingface':
        headers['User-Agent'] = 'AgentCityPanel/0.4'
    key = _key(key_reader, provider) if source["accountCatalog"] else None
    if source["accountCatalog"] and not key:
        raise ValueError("catalog key required")
    if key and source["accountCatalog"]:
        headers["Authorization" if source["auth"] == "bearer" else "x-goog-api-key"] = (
            "Bearer " + key if source["auth"] == "bearer" else key
        )
    if provider != "gemini":
        _raw, payload = _read_json(source["url"], headers, MAX_JSON)
        return normalize(provider, payload)
    models: list[Any] = []
    total_bytes = 0
    token: str | None = None
    seen_tokens: set[str] = set()
    for _page in range(MAX_GEMINI_PAGES):
        page_url = _with_query(source["url"], pageSize="1000", **({"pageToken": token} if token else {}))
        raw, payload = _read_json(page_url, headers, MAX_JSON - total_bytes)
        total_bytes += len(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("Gemini catalogue has no model list")
        models.extend(payload["models"])
        if len(models) > MAX_MODELS:
            raise ValueError("Gemini catalogue has too many models")
        next_token = payload.get("nextPageToken")
        if not next_token:
            return normalize(provider, {"models": models})
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise ValueError("Gemini catalogue pagination token is invalid")
        seen_tokens.add(next_token)
        token = next_token
    raise ValueError("Gemini catalogue pagination limit exceeded")


def _text(value: Any, limit: int = 180) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _number(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            return int(value)
    return None


def _developer(model_id: str, item: Mapping[str, Any]) -> str:
    family = model_id.rsplit("/", 1)[-1].lower()
    for prefix, developer in (("qwen-", "qwen"), ("zai-glm", "zai"),
                              ("deepseek", "deepseek"), ("moonshot", "moonshotai")):
        if family.startswith(prefix):
            return developer
    owner = item.get("owned_by") or item.get("developer")
    if isinstance(owner, str) and owner:
        return owner
    return model_id.split("/", 1)[0] if "/" in model_id else "unknown"


def _chinese(developer: str) -> bool:
    low = developer.lower()
    return low in _CHINESE or any(part in low for part in ("qwen", "deepseek", "moonshot", "minimax", "glm"))


def _non_chat(model_id: str, item: Mapping[str, Any]) -> bool:
    value = (model_id + " " + _text(item.get("name"))).lower()
    return any(word in value for word in ("embedding", "embed", "rerank", "bge-", "e5-", "gte-", "whisper", "speech", "audio", "tts", "text-to-image", "text-to-video", "image-to-image", "stable-diffusion", "flux.", "kolors", "video"))


def _row(model_id: str, item: Mapping[str, Any], *, developer: str | None = None,
         name: str | None = None, context: Any = None, tools: Any = None,
         vision: Any = False) -> dict[str, Any]:
    dev = developer or _developer(model_id, item)
    display_name = _text(name) or _text(item.get("displayName")) or _text(item.get("name")) or model_id
    return {"id": model_id, "name": display_name.removeprefix("models/"),
            "developer": dev, "chinese": _chinese(dev), "context": _number(context, item.get("context_length"), item.get("context_window"), item.get("max_context_length")),
            "tools": tools if isinstance(tools, bool) else None, "vision": bool(vision),
            "priceVerified": False, "kind": "chat"}


def normalize(provider: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a provider response; malformed or non-chat entries are counted."""
    if not isinstance(payload, Mapping):
        raise ValueError("catalog must be an object")
    entries = payload.get("models") if provider == "gemini" else payload.get("data")
    if not isinstance(entries, list):
        raise ValueError("catalog has no model list")
    if provider == "gemini" and payload.get("nextPageToken"):
        raise ValueError("Gemini catalogue is paginated")
    result: list[dict[str, Any]] = []
    skipped = 0
    for item in entries[:2000]:
        if not isinstance(item, Mapping):
            skipped += 1
            continue
        raw_id = item.get("name") if provider == "gemini" else item.get("id")
        if not isinstance(raw_id, str) or not raw_id or len(raw_id) > 200:
            skipped += 1
            continue
        if provider == "gemini":
            methods = item.get("supportedGenerationMethods")
            if not isinstance(methods, list) or "generateContent" not in methods:
                skipped += 1
                continue
            model_id = raw_id.removeprefix("models/")
            result.append(_row(model_id, item, developer="google", name=item.get("displayName"),
                               context=item.get("inputTokenLimit"),
                               tools=True if "functionCalling" in methods else None,
                               vision="image" in str(item.get("description", "")).lower()))
            continue
        if _non_chat(raw_id, item):
            skipped += 1
            continue
        if provider == "huggingface":
            upstreams = []
            for upstream in item.get('providers', [])[:40] if isinstance(item.get('providers'), list) else []:
                if not isinstance(upstream, Mapping) or upstream.get('status') != 'live':
                    continue
                upstreams.append({'name': _text(upstream.get('provider')), 'context': _number(upstream.get('context_length')),
                                  'tools': upstream.get('supports_tools') if isinstance(upstream.get('supports_tools'), bool) else None})
            if not upstreams:
                skipped += 1
                continue
            row = _row(raw_id, item)
            row['name'] = raw_id
            row['upstreams'] = upstreams
            result.append(row)
            continue
        if provider == "mistral":
            capabilities = item.get("capabilities")
            if not isinstance(capabilities, Mapping) or capabilities.get("completion_chat") is not True:
                skipped += 1
                continue
        params = item.get("supported_parameters")
        caps = item.get("capabilities")
        tools = True if isinstance(params, list) and ("tools" in params or "tool_choice" in params) else None
        if isinstance(caps, Mapping) and isinstance(caps.get("function_calling"), bool):
            tools = caps["function_calling"]
        modalities = item.get("architecture", {}).get("input_modalities", []) if isinstance(item.get("architecture"), Mapping) else []
        result.append(_row(raw_id, item, context=item.get("context_length") or item.get("context_window") or item.get("max_context_length"),
                           tools=tools, vision="image" in modalities or "vision" in raw_id.lower()))
    return {"models": result, "skippedCount": skipped}


__all__ = ["SOURCES", "fetch", "normalize"]
