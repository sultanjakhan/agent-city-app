"""Explicit one-pass audit; stores receipts without credentials in a chosen panel profile."""
import argparse
from pathlib import Path
import json
import access
from server import Store, PROVIDERS, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.data_dir)
    for provider in PROVIDERS:
        store._refresh_one(provider)
        rows = store.state["catalogs"].get(provider, {}).get("models", [])
        halt = None
        for model in rows:
            if halt:
                result = {"provider": provider, "model": model["id"], "status": "skipped", "sent": False,
                          "attemptedAt": now(), "detail": halt}
            else:
                result = access.probe(provider, model["id"], store.catalog_fetcher)
                if result["status"] in {"rate_limited", "forbidden", "auth_error", "payment_required", "missing_key", "credential_error", "catalog_error"}:
                    halt = "Не проверена: " + result["detail"].lower()
            store.state["checks"][provider + "|" + model["id"]] = result
            store.save()
            print(json.dumps({"provider": provider, "model": model["id"], "status": result["status"], "sent": result["sent"]}), flush=True)
    # Do not start a server or run model requests in the background after the audit.


if __name__ == "__main__":
    main()
