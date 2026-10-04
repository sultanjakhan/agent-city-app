"""Bounded synthetic API smoke checks. No user prompts, tools, retries or paid fallback."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from panel_keys import key_available, read_key
ENDPOINTS = {"openrouter": "https://openrouter.ai/api/v1/chat/completions",
             "kilo": "https://api.kilo.ai/api/gateway/chat/completions",
             "cline": "https://api.cline.bot/api/v1/chat/completions",
             "zen": "https://opencode.ai/zen/v1/chat/completions"}
PROMPT = "Output only the following literal text, with nothing added: CITY_OK_4"
MARKER = "CITY_OK_4"
MAX_RESPONSE = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise URLError("redirect disabled")


def verify_openrouter_key(key_reader=read_key, opener=None):
    """Read-only key validation; never retain account data from /api/v1/key."""
    try:
        key = key_reader("openrouter")
        if not key:
            return {"status": "missing_key"}
        request = Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
        with (opener or build_opener(NoRedirect())).open(request, timeout=15) as response:
            raw = response.read(MAX_RESPONSE + 1)
        data = json.loads(raw) if len(raw) <= MAX_RESPONSE else None
        return {"status": "accepted" if isinstance(data, dict) and isinstance(data.get("data"), dict) else "unverified"}
    except HTTPError as exc:
        return {"status": {401: "rejected", 403: "forbidden", 429: "rate_limited"}.get(exc.code, "unverified")}
    except Exception:
        return {"status": "unverified"}


def clients():
    """Installation evidence only; not proof of an authenticated IDE session."""
    root = Path.home() / ".vscode/extensions"
    names = [p.name for p in root.iterdir()] if root.is_dir() else []
    result = []
    for ident, name, prefix, docs in [
        ("cline", "Cline", "saoudrizwan.claude-dev-", "https://docs.cline.bot/provider-config/openrouter"),
        ("kilo", "Kilo Code", "kilocode.kilo-code-", "https://kilo.ai/docs/getting-started/using-kilo-for-free"),
        ("opencode", "OpenCode", "sst-dev.opencode-", "https://opencode.ai/docs/ide/")]:
        installed = sorted(x for x in names if x.startswith(prefix))
        result.append({"id": ident, "name": name, "extensionInstalled": bool(installed),
                       "cliInstalled": bool(shutil.which(ident)), "docs": docs})
    return result


def probe(provider, model_id, catalog_fetcher, key_reader=read_key, opener=None):
    started = time.monotonic()
    record = {"provider": provider, "model": model_id, "attemptedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "status": "unverified", "sent": False, "reply": "", "finishReason": None, "prompt": PROMPT}
    def done(status, detail, **extra):
        record.update(status=status, detail=detail, durationMs=round((time.monotonic()-started)*1000), **extra)
        return record
    if provider not in ENDPOINTS:
        return done("price_unverified", "Каталог подключён; бесплатная квота аккаунта не подтверждена. Запрос не отправлен.")
    try:
        key = None if provider == "kilo" else key_reader(provider)
        if provider != "kilo" and not key:
            return done("missing_key", "Нужен API-ключ")
    except Exception:
        return done("credential_error", "Не удалось прочитать ключ этого пользователя")
    try:
        # Every single inference rechecks THIS provider's live free list. A :free name is insufficient.
        catalog = catalog_fetcher(provider)
        model = next((m for m in catalog["models"] if m["id"] == model_id), None)
        if not model or model.get("priceVerified") is not True or model.get("kind", "chat") != "chat":
            return done("price_unverified", "Бесплатный текстовый API не подтверждён; запрос не отправлен")
    except Exception:
        return done("catalog_error", "Не удалось проверить текущий тариф; запрос не отправлен")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    body = {"model": model_id, "messages": [{"role": "user", "content": PROMPT}], "stream": False, "max_tokens": 256}
    if provider == "openrouter":
        body["provider"] = {"allow_fallbacks": False, "max_price": {"prompt": 0, "completion": 0}}
    request = Request(ENDPOINTS[provider], data=json.dumps(body).encode(), headers=headers, method="POST")
    record["sent"] = True
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            return done("invalid_response", "Слишком большой ответ")
        payload = json.loads(raw)
        choice = payload.get("choices", [None])[0]
        content = choice.get("message", {}).get("content") if isinstance(choice, dict) else None
        finish = choice.get("finish_reason") if isinstance(choice, dict) else None
        record["finishReason"] = finish if isinstance(finish, str) else None
        if not isinstance(content, str) or not content.strip():
            return done("empty", "API ответил, но итогового текста нет")
        record["reply"] = content[:500]
        if finish != "stop":
            return done("incomplete", "Ответ не завершён штатно")
        if content.strip() != MARKER:
            return done("mismatch", "Текст получен, но контрольный ответ не совпал")
        return done("ok", "Контрольный ответ получен")
    except HTTPError as exc:
        status, detail = {401: ("auth_error", "Ключ не принят"), 402: ("payment_required", "Провайдер требует оплату"),
                          403: ("forbidden", "Доступ отклонён"), 429: ("rate_limited", "Лимит запросов")}.get(exc.code, ("http_error", "Ошибка API"))
        return done(status, f"{detail} · HTTP {exc.code}", httpStatus=exc.code)
    except (TimeoutError, URLError) as exc:
        return done("timeout" if isinstance(exc, TimeoutError) else "network_error", "Нет ответа от API за время проверки")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return done("invalid_response", "API вернул неожиданный формат")
