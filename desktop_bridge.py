"""Private inherited-pipe adapter for the native host; no public listener."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from owner_broker import OwnerBroker

MAX_MESSAGE = 256 * 1024
CONTROL_MESSAGE = 16384
MAX_REPLY = 1024 * 1024


def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate field")
        out[key] = value
    return out


def request(raw, expected):
    if len(raw) > MAX_MESSAGE or not raw.endswith(b"\n"):
        raise ValueError("frame")
    value = json.loads(raw, object_pairs_hook=pairs)
    fields = {"version", "id", "action", "draftsClosed"}
    if type(value) is dict and value.get("action") == "agent-request":
        fields.add("request")
    if type(value) is not dict or set(value) != fields:
        raise ValueError("fields")
    if type(value["version"]) is not int or value["version"] != 1 or type(value["id"]) is not int or value["id"] != expected:
        raise ValueError("sequence")
    if value["action"] != "agent-request" and len(raw) > CONTROL_MESSAGE:
        raise ValueError("control frame")
    if type(value["draftsClosed"]) is not bool or value["action"] not in ("bootstrap", "revoke", "stop", "restart", "status", "agent-request"):
        raise ValueError("action")
    if value["action"] in ("stop", "restart") and value["draftsClosed"] is not True:
        raise ValueError("explicit draft closure required")
    return value


def send(value):
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(raw) > MAX_REPLY:
        raise ValueError("response limit")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime", choices=("normal", "local-only"), default="local-only")
    args = parser.parse_args(argv)
    config = args.config.resolve(strict=True)
    if not config.is_file():
        return 2
    environment = dict(os.environ)
    # Explicit profile wins; no automatic discovery, import or new-folder prompt.
    for key in ("AGENT_CITY_DATA_ROOT", "AGENT_CITY_PANEL_DATA", "AGENT_CITY_SKILLS_ROOT", "AGENT_CITY_CREDENTIALS_DIR", "CODEX_HOME"):
        environment.pop(key, None)
    environment["AGENT_CITY_CONFIG"] = str(config)
    root = Path(__file__).resolve().parent
    handoff = []
    def capture(url, instance, **options):
        handoff[:] = [url]
    local_only = args.runtime == "local-only"
    broker = OwnerBroker(root, 0, environment, capture, local_only=local_only)
    try:
        ready = broker.start()
        send({"version":1, "kind":"ready", "port":ready["port"], "ownerHost":broker.owner_host, "localOnly":local_only})
        sequence = 1
        while True:
            raw = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
            if not raw:
                break
            try:
                message = request(raw, sequence)
                sequence += 1
                deadline = time.monotonic() + 30
                action = message["action"]
                if action == "agent-request":
                    # This is the surviving trusted controller's own CLI child.
                    # The broker's exact grant allowlist remains authoritative.
                    try:
                        incoming = message["request"]
                        if type(incoming) is not dict or set(incoming) != {"method", "path", "body"}:
                            raise ValueError("unsupported request")
                        result = broker.run_cli(incoming["method"], incoming["path"], incoming["body"], deadline=deadline)
                    except Exception:
                        result = {"isError": True, "error": "agent_request_rejected_or_outcome_unknown"}
                elif action == "status":
                    result = {"backendAlive":bool(broker.child and broker.child.poll() is None), "localOnly":local_only}
                elif action == "bootstrap":
                    broker.recover_browser(deadline=deadline)
                    result = {"url":handoff.pop()}
                elif action == "revoke":
                    result = broker.rpc("revoke", deadline=deadline)
                elif action == "restart":
                    if broker.child and broker.child.poll() is not None:
                        broker._terminate_own_child(deadline=deadline)
                        broker.start(deadline=deadline)
                        broker.recover_browser(deadline=deadline)
                    else:
                        broker.restart(drafts_closed=True, deadline=deadline)
                    result = {"url":handoff.pop(), "port":broker.port, "ownerHost":broker.owner_host}
                else:
                    broker.stop(drafts_closed=True, deadline=deadline)
                    send({"version":1, "id":message["id"], "ok":True, "result":{"stopped":True}})
                    return 0
                send({"version":1, "id":message["id"], "ok":True, "result":result})
            except Exception:
                # No incoming payloads, URLs, grants or exception text are logged.
                broker._retire_channel()
                send({"version":1, "kind":"failed", "error":"desktop_control_refused"})
                return 3
    except Exception:
        return 2
    finally:
        broker._retire_channel()
        if broker.child:
            # EOF causes the existing server control to revoke, fence and drain
            # accepted writes before shutdown. Never terminate an in-flight write.
            try:
                broker.child.wait(timeout=30)
                broker._close_streams()
            except Exception:
                # Retain ownership until drainage completes, even if host died.
                broker.child.wait()
                broker._close_streams()
    return 0
