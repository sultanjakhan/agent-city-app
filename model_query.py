"""Read-only, bounded model-route queries over a captured panel snapshot."""

import hashlib
import json
from collections.abc import Mapping

from public_api import models


_ALLOWED = {
    "provider", "developer", "q", "kind", "tools", "vision", "priceVerified",
    "authStatus", "responseStatus", "limit", "offset", "revision",
}
_BOOL_FILTERS = {"tools", "vision", "priceVerified"}
_MAX_LIMIT = 50
_MAX_OFFSET = 10_000


def http_params(query):
    if set(query) - _ALLOWED or any(len(v) != 1 for v in query.values()):
        raise ValueError('invalid parameters')
    result = {k: v[0] for k, v in query.items()}
    for key in ('limit', 'offset'):
        if key in result:
            if not result[key].isdigit():
                raise ValueError('invalid pagination')
            result[key] = int(result[key])
    for key in _BOOL_FILTERS:
        if key in result:
            if result[key] not in {'true', 'false'}:
                raise ValueError('invalid boolean')
            result[key] = result[key] == 'true'
    return result


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _revision(snapshot):
    """Revision of catalogue evidence, independent of response time and page."""
    metadata = {
        "sources": snapshot.get("sources", []),
        "credentials": snapshot.get("credentials", {}),
        "catalogs": snapshot.get("catalogs", {}),
        "checks": snapshot.get("checks", {}),
    }
    return hashlib.sha256(_canonical(metadata).encode("utf-8")).hexdigest()


def _strict_params(params):
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise ValueError("params must be a mapping")
    unknown = set(params) - _ALLOWED
    if unknown:
        raise ValueError("unknown query args: " + ", ".join(sorted(map(str, unknown))))

    result = dict(params)
    for key in ("provider", "developer", "q", "kind", "authStatus", "responseStatus", "revision"):
        if key in result and not isinstance(result[key], str):
            raise ValueError(f"{key} must be a string")
        if key in result and len(result[key]) > 200:
            raise ValueError('filter too long')
    for key in _BOOL_FILTERS:
        if key in result and not isinstance(result[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key, default, upper in (("limit", 20, _MAX_LIMIT), ("offset", 0, _MAX_OFFSET)):
        value = result.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise ValueError(f"{key} must be an integer between 0 and {upper}")
        if key == "limit" and value == 0:
            raise ValueError("limit must be between 1 and 50")
        result[key] = value
    return result


def _contains(value, query):
    return query.casefold() in str(value or "").casefold()


def _evidence(route, snapshot):
    provider = route["provider"]
    model_id = route["id"]
    catalog = snapshot.get("catalogs", {}).get(provider, {})
    source = next((item for item in snapshot.get("sources", []) if item.get("id") == provider), {})
    check = snapshot.get("checks", {}).get(provider + "|" + model_id, {})
    model_data = next((item for item in catalog.get("models", []) if item.get("id") == model_id), {})
    price_date = model_data.get("priceVerifiedAt") or catalog.get("priceVerifiedAt")
    return {
        "catalog": {"member": True, "date": catalog.get("updatedAt")},
        "price": {
            "verified": bool(model_data.get("priceVerified", False)),
            "date": price_date,
            "status": "verified" if model_data.get("priceVerified") is True else "unverified",
        },
        "auth": {
            "hasKey": bool(snapshot.get("credentials", {}).get(provider, False)),
            "authStatus": catalog.get("authStatus", "unverified"),
        },
        "quota": {"status": "unknown"},
        "inference": {
            "status": check.get("status"),
            "date": check.get("attemptedAt"),
        },
        "source": {"catalogUrl": source.get("catalogUrl")},
    }


def page_models(snapshot, params=None):
    """Filter and paginate the public model contract without making API calls."""
    query = _strict_params(params)
    revision = _revision(snapshot)
    if query.get("revision") and query["revision"] != revision:
        raise ValueError("stale revision")

    rows = []
    for route in models(snapshot)["routes"]:
        if "provider" in query and route.get("provider") != query["provider"]:
            continue
        if "developer" in query and not _contains(route.get("developer"), query["developer"]):
            continue
        if "q" in query and not any(_contains(route.get(field), query["q"]) for field in ("id", "name", "developer", "provider")):
            continue
        if "kind" in query and route.get("kind") != query["kind"]:
            continue
        if any(key in query and route.get(key) != query[key] for key in _BOOL_FILTERS):
            continue
        evidence = _evidence(route, snapshot)
        if "authStatus" in query and evidence["auth"]["authStatus"] != query["authStatus"]:
            continue
        if "responseStatus" in query and evidence["inference"]["status"] != query["responseStatus"]:
            continue
        rows.append({**route, "evidence": evidence})

    rows.sort(key=lambda row: (str(row.get("provider", "")), str(row.get("id", ""))))
    offset, limit = query["offset"], query["limit"]
    return {
        "schemaVersion": 1,
        "asOf": snapshot.get("serverTime"),
        "revision": revision,
        "total": len(rows),
        "nextOffset": offset + limit if offset + limit < len(rows) else None,
        "routes": rows[offset:offset + limit],
    }
