#!/usr/bin/env python3
"""Small, bounded adapter for local Ollama and explicitly free cloud models.

This module deliberately has no tool execution, retries, model downloads, or
fallback routing.  It is intended to return text for a caller to review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
KILO_MODELS_URL = "https://api.kilo.ai/api/gateway/models"
KILO_CHAT_URL = "https://api.kilo.ai/api/gateway/chat/completions"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
MAX_INPUT_CHARS = 16_384
MAX_OUTPUT_TOKENS = 2_048
HTTP_TIMEOUT_SECONDS = 60
ALLOWED_ENDPOINTS = {
    OLLAMA_TAGS_URL,
    OLLAMA_GENERATE_URL,
    OPENROUTER_MODELS_URL,
    OPENROUTER_CHAT_URL,
    KILO_MODELS_URL,
    KILO_CHAT_URL,
}
PRICE_FIELDS = (
    "prompt",
    "completion",
    "request",
    "image",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any):
        raise URLError("redirects disabled")


def urlopen(request: Request, *, timeout: int):
    """Open only the requested endpoint; do not forward Authorization on redirects."""
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


class WorkerError(RuntimeError):
    """An expected, user-facing policy or transport failure."""


def _safe_http_error(exc: BaseException) -> str:
    """Return a short error that cannot echo headers, request bodies, or keys."""
    if isinstance(exc, HTTPError):
        return f"HTTP request failed with status {exc.code}"
    if isinstance(exc, URLError):
        return "HTTP request could not reach the provider"
    if isinstance(exc, TimeoutError):
        return "HTTP request timed out"
    return "HTTP request failed"


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """Make one bounded JSON request; callers decide whether to retry (they do not)."""
    if url not in ALLOWED_ENDPOINTS:
        raise WorkerError("Provider endpoint is not allowed")
    data = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except Exception as exc:  # urllib has several concrete transport exceptions
        raise WorkerError(_safe_http_error(exc)) from None
    if len(raw) > 4 * 1024 * 1024:
        raise WorkerError("Provider response exceeded the 4 MiB safety limit")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WorkerError("Provider returned invalid JSON") from None


def _model_name(item: Mapping[str, Any]) -> str | None:
    for key in ("name", "model", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _ollama_model_names(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), list):
        raise WorkerError("Ollama returned an unexpected model catalog")
    names: list[str] = []
    for item in payload["models"]:
        if isinstance(item, Mapping):
            name = _model_name(item)
            if name and name not in names:
                names.append(name)
    return names


def _is_zero(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return Decimal(str(value)) == Decimal("0")
    except (InvalidOperation, ValueError):
        return False


def _zero_priced_text_reason(item: Mapping[str, Any], *, require_free_suffix: bool) -> str | None:
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    if require_free_suffix and not model_id.lower().endswith(":free"):
        return None
    pricing = item.get("pricing")
    if not isinstance(pricing, Mapping):
        return None
    # :free is only a label; it never replaces a live pricing guard.
    if not all(field in pricing and _is_zero(pricing[field]) for field in ("prompt", "completion")):
        return None
    if any(not _is_zero(value) for value in pricing.values()):
        return None
    suffix = " (:free ID)" if model_id.lower().endswith(":free") else ""
    return f"prompt/completion and all present billable fields are verified zero{suffix}"


def _openrouter_free_reason(item: Mapping[str, Any]) -> str | None:
    return _zero_priced_text_reason(item, require_free_suffix=False)


def _kilo_free_reason(item: Mapping[str, Any]) -> str | None:
    return _zero_priced_text_reason(item, require_free_suffix=True)


def _is_text_chat_capable(item: Mapping[str, Any]) -> bool:
    """Require catalog evidence for text input and text output."""
    architecture = item.get("architecture")
    if not isinstance(architecture, Mapping):
        return False
    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")
    if isinstance(input_modalities, list) and isinstance(output_modalities, list):
        inputs = {str(value).lower() for value in input_modalities}
        outputs = {str(value).lower() for value in output_modalities}
        return "text" in inputs and outputs == {"text"}
    modality = architecture.get("modality")
    if isinstance(modality, str) and "->" in modality:
        input_side, output_side = modality.lower().split("->", 1)
        return "text" in input_side.split("+") and output_side == "text"
    return False


def _is_dynamic_or_aggregated_id(model_id: str) -> bool:
    """Reject routing aliases whose backend/model can change between calls."""
    lowered = model_id.lower()
    if lowered in {"openrouter/free", "openrouter/auto"}:
        return True
    tokens = {token for token in re.split(r"[/_:\-.]+", lowered) if token}
    return bool(tokens & {"router", "auto", "aggregate", "aggregator", "aggregation"})


def _openrouter_model_stats(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise WorkerError("OpenRouter returned an unexpected model catalog")
    result: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in payload["data"]:
        if not isinstance(item, Mapping):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        free_reason = _openrouter_free_reason(item)
        if free_reason is None:
            continue
        if _is_dynamic_or_aggregated_id(model_id):
            skipped.append({"id": model_id, "reason": "dynamic or aggregated route"})
            continue
        if not _is_text_chat_capable(item):
            skipped.append({"id": model_id, "reason": "not verified text-chat capable"})
            continue
        # Keep the catalog sanitized and useful: no descriptions or provider metadata.
        result.append({"id": model_id, "free_reason": free_reason})
    return result, skipped


def _openrouter_models(payload: Any) -> list[dict[str, Any]]:
    return _openrouter_model_stats(payload)[0]


def _kilo_model_stats(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise WorkerError("Kilo returned an unexpected model catalog")
    result: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in payload["data"]:
        if not isinstance(item, Mapping):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        free_reason = _kilo_free_reason(item)
        if free_reason is None:
            continue
        if _is_dynamic_or_aggregated_id(model_id):
            skipped.append({"id": model_id, "reason": "dynamic or aggregated route"})
            continue
        if not _is_text_chat_capable(item):
            skipped.append({"id": model_id, "reason": "not verified text-chat capable"})
            continue
        result.append({"id": model_id, "free_reason": free_reason})
    return result, skipped


def _kilo_models(payload: Any) -> list[dict[str, Any]]:
    return _kilo_model_stats(payload)[0]


def _read_catalogs() -> tuple[list[str], list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], list[dict[str, str]], dict[str, str | None]]:
    errors: dict[str, str | None] = {"ollama": None, "openrouter": None, "kilo": None}
    local_names: list[str] = []
    free_models: list[dict[str, Any]] = []
    skipped_models: list[dict[str, str]] = []
    kilo_models: list[dict[str, Any]] = []
    kilo_skipped: list[dict[str, str]] = []
    try:
        local_names = _ollama_model_names(request_json(OLLAMA_TAGS_URL))
    except WorkerError as exc:
        errors["ollama"] = str(exc)
    try:
        free_models, skipped_models = _openrouter_model_stats(request_json(OPENROUTER_MODELS_URL))
    except WorkerError as exc:
        errors["openrouter"] = str(exc)
    try:
        kilo_models, kilo_skipped = _kilo_model_stats(request_json(KILO_MODELS_URL))
    except WorkerError as exc:
        errors["kilo"] = str(exc)
    return local_names, free_models, skipped_models, kilo_models, kilo_skipped, errors


def build_catalog() -> dict[str, Any]:
    local_names, free_models, skipped_models, kilo_models, kilo_skipped, errors = _read_catalogs()
    candidates = [{"provider": "ollama", "model": name, "free_reason": "local model"} for name in local_names]
    candidates.extend(
        {"provider": "openrouter", "model": item["id"], "free_reason": item["free_reason"]}
        for item in free_models
    )
    candidates.extend(
        {"provider": "kilo", "model": item["id"], "free_reason": item["free_reason"]}
        for item in kilo_models
    )
    return {
        "providers": {
            "ollama": {"available": errors["ollama"] is None, "models": local_names},
            "openrouter": {
                "available": errors["openrouter"] is None,
                "models": free_models,
                "auth_available": bool(os.environ.get(OPENROUTER_KEY_ENV)),
            },
            "kilo": {
                "available": errors["kilo"] is None,
                "models": kilo_models,
                "auth_available": False,
                "auth_required": False,
                "live_inference_verified": False,
                "live_inference_note": "Catalog discovery does not test inference or available quota; inspect a separate run receipt.",
            },
        },
        "free_candidates": candidates,
        "catalog_skipped": {
            "openrouter_free_but_not_eligible": skipped_models,
            "kilo_free_but_not_eligible": kilo_skipped,
        },
        "local_loaded_models": local_names,
        "errors": {name: value for name, value in errors.items() if value},
        "policy": {
            "max_input_chars": MAX_INPUT_CHARS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "automatic_retries": False,
            "automatic_fallbacks": False,
            "external_responses_are_text_only": True,
        },
    }


def _read_prompt(path: str) -> str:
    prompt_path = Path(path)
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError:
        raise WorkerError("Could not read prompt file as UTF-8") from None
    if len(prompt) > MAX_INPUT_CHARS:
        raise WorkerError(f"Prompt exceeds the {MAX_INPUT_CHARS}-character limit")
    return prompt


def _write_json(path: str, value: Mapping[str, Any], *, overwrite: bool) -> None:
    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise WorkerError("Output file exists; pass --overwrite to replace it")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if overwrite else "x"
        with output_path.open(mode, encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        raise WorkerError("Output file exists; pass --overwrite to replace it") from None
    except OSError:
        raise WorkerError("Could not write output file") from None


def _reserve_output(path: str, *, overwrite: bool):
    """Reserve a run receipt before spending provider time or quota."""
    output_path = Path(path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and output_path.exists():
            return output_path.open("r+", encoding="utf-8", newline="\n"), False
        return output_path.open("x", encoding="utf-8", newline="\n"), True
    except FileExistsError:
        raise WorkerError("Output file exists; pass --overwrite to replace it") from None
    except OSError:
        raise WorkerError("Could not reserve output file") from None


def _write_reserved(stream, value: Mapping[str, Any]) -> None:
    try:
        stream.seek(0)
        stream.truncate()
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
    except OSError:
        raise WorkerError("Could not write output file") from None


def _extract_ollama_result(payload: Any) -> tuple[str, dict[str, Any] | None, str | None]:
    if not isinstance(payload, Mapping):
        raise WorkerError("Ollama returned an unexpected response")
    response = payload.get("response")
    if not isinstance(response, str):
        raise WorkerError("Ollama response did not contain text")
    token_values = {key: payload[key] for key in ("prompt_eval_count", "eval_count") if key in payload}
    tokens = token_values or None
    finish_reason = payload.get("done_reason")
    return response, tokens, finish_reason if isinstance(finish_reason, str) else None


def _extract_openrouter_result(payload: Any) -> tuple[str, dict[str, Any] | None, str | None]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("choices"), list) or not payload["choices"]:
        raise WorkerError("OpenRouter returned an unexpected response")
    choice = payload["choices"][0]
    if not isinstance(choice, Mapping):
        raise WorkerError("OpenRouter returned an unexpected response")
    message = choice.get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise WorkerError("OpenRouter response did not contain text")
    usage = payload.get("usage")
    tokens = dict(usage) if isinstance(usage, Mapping) else None
    finish_reason = choice.get("finish_reason")
    return message["content"], tokens, finish_reason if isinstance(finish_reason, str) else None


def _run_ollama(model: str, prompt: str, *, json_format: bool) -> tuple[str, dict[str, Any] | None, str | None]:
    names = _ollama_model_names(request_json(OLLAMA_TAGS_URL))
    if model not in names:
        raise WorkerError("Requested Ollama model is not loaded locally")
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": MAX_OUTPUT_TOKENS},
    }
    if json_format:
        body["format"] = "json"
    # No tools, shell, file, or write instructions are sent to the model.
    return _extract_ollama_result(request_json(OLLAMA_GENERATE_URL, method="POST", body=body))


def _run_openrouter(model: str, prompt: str) -> tuple[str, dict[str, Any] | None, str | None]:
    key = os.environ.get(OPENROUTER_KEY_ENV)
    if not key:
        raise WorkerError(f"Set {OPENROUTER_KEY_ENV} before using provider openrouter")
    # Recheck the public catalog immediately before every call; never trust a stale list.
    catalog = _openrouter_models(request_json(OPENROUTER_MODELS_URL))
    by_id = {item["id"]: item for item in catalog}
    if model not in by_id:
        raise WorkerError("Requested OpenRouter model is not verified free in the live catalog")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {key}"}
    # No plugins/tools are present, and the exact caller model is always retained.
    return _extract_openrouter_result(request_json(OPENROUTER_CHAT_URL, method="POST", body=body, headers=headers))


def _run_kilo(model: str, prompt: str) -> tuple[str, dict[str, Any] | None, str | None]:
    # Anonymous Kilo access is restricted to exact, catalog-verified :free IDs.
    catalog = _kilo_models(request_json(KILO_MODELS_URL))
    by_id = {item["id"]: item for item in catalog}
    if model not in by_id:
        raise WorkerError("Requested Kilo model is not verified free in the live catalog")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
    }
    # Deliberately no Authorization header and no retry/fallback.
    return _extract_openrouter_result(request_json(KILO_CHAT_URL, method="POST", body=body))


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    if args.data_class not in {"synthetic", "public"}:
        raise WorkerError("Only synthetic or public data-class values are permitted")
    prompt_path = Path(args.prompt_file).resolve()
    output_path = Path(args.output).resolve()
    if prompt_path == output_path:
        raise WorkerError("Prompt and output paths must be different")
    prompt = _read_prompt(args.prompt_file)
    output_stream, output_was_new = _reserve_output(args.output, overwrite=args.overwrite)
    started = time.monotonic()
    try:
        if args.provider == "ollama":
            response, tokens, finish_reason = _run_ollama(args.model, prompt, json_format=args.json_format)
        elif args.provider == "openrouter":
            response, tokens, finish_reason = _run_openrouter(args.model, prompt)
        else:
            response, tokens, finish_reason = _run_kilo(args.model, prompt)
        receipt: dict[str, Any] = {
            "provider": args.provider,
            "model": args.model,
            "data_class": args.data_class,
            "final_response": response,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "response_handling": "text_only_not_executed_or_applied",
        }
        if tokens is not None:
            receipt["tokens"] = tokens
        if finish_reason is not None:
            receipt["finish_reason"] = finish_reason
        _write_reserved(output_stream, receipt)
        return receipt
    except WorkerError:
        if output_was_new:
            try:
                output_stream.close()
                Path(args.output).unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        if not output_stream.closed:
            output_stream.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded local/free external-model worker")
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog", help="inventory loaded Ollama and verified-free cloud models")
    catalog.add_argument("--output", help="optional JSON catalog output path")
    catalog.add_argument("--overwrite", action="store_true", help="allow replacing an existing output")
    run = sub.add_parser("run", help="run one bounded text request")
    run.add_argument("--provider", choices=("ollama", "openrouter", "kilo"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--prompt-file", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--data-class", choices=("synthetic", "public"), required=True)
    run.add_argument("--overwrite", action="store_true", help="allow replacing an existing output")
    run.add_argument("--json-format", action="store_true", help="request JSON response format from Ollama")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            value = build_catalog()
            if args.output:
                _write_json(args.output, value, overwrite=args.overwrite)
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            value = run_once(args)
            print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except WorkerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
