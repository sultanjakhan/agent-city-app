"""Accept external-storage isolation using synthetic, temporary data only."""
from __future__ import annotations
import hashlib
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import socket
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, build_opener, ProxyHandler

APP = Path(__file__).resolve().parents[1]
EXCLUDES = {".git", "__pycache__", "node_modules", "test-results", "playwright-report", ".venv"}
OWNER_HEADERS = {}
SECRET_NAMES = {"OPENROUTER_API_KEY", "CLINE_API_KEY", "OPENCODE_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "SILICONFLOW_API_KEY", "HF_TOKEN"}


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not any(x in EXCLUDES for x in p.relative_to(root).parts)}


def scan():
    findings = []
    private_dirs = {".local", "local", "private", "keys", "profiles", "sessions", "backups", "exports", "logs"}
    private_patterns = {"storage.local.json", "connection.local.json", "credentials.*", "secrets.*", ".env", ".env.*", "*.dpapi", "*.pem", "*.key", "*.p12", "*.pfx", "*.db", "*.db-*", "*.sqlite*", "*.jsonl", "*.log", "*.bak", "*.backup"}
    pending = [APP]
    files = []
    while pending:
        folder = pending.pop()
        for entry in os.scandir(folder):
            p = Path(entry.path)
            relative = p.relative_to(APP).as_posix()
            stat = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                findings.append({"file": relative, "category": "unreviewed-reparse"})
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name in EXCLUDES:
                    continue
                if entry.name.lower() in private_dirs:
                    findings.append({"file": relative, "category": "private-directory"})
                    continue
                pending.append(p)
            elif entry.is_file(follow_symlinks=False):
                files.append(p)
    for p in files:
        if p.name.lower() != ".env.example" and any(fnmatch.fnmatch(p.name.lower(), pattern) for pattern in private_patterns):
            findings.append({"file": p.relative_to(APP).as_posix(), "category": "private-file"})
            # Report metadata only; never open private candidates.
            continue
        try:
            content = p.read_text("utf-8")
        except UnicodeError:
            findings.append({"file": p.relative_to(APP).as_posix(), "category": "unreviewed-binary"})
            continue
        # These are detection heuristics, not an exhaustive secret scanner.
        for category, pattern in {
            "personal-path": r"[A-Za-z]:[/\\]Users[/\\]|/Users/[A-Za-z]|/home/[A-Za-z]",
            "credential-format": r"sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{25,}|" + chr(45) * 5 + "BEGIN .*PRIVATE KEY" + chr(45) * 5,
        }.items():
            lines = [i for i, line in enumerate(content.splitlines(), 1) if re.search(pattern, line)]
            if lines:
                findings.append({"file": p.relative_to(APP).as_posix(), "category": category, "lines": lines})
    return findings


def request(url, body=None, token=None):
    headers = dict(OWNER_HEADERS)
    if body is not None: headers.update({"Content-Type": "application/json", "X-Agent-City": "1"})
    if token:
        headers["X-Agent-City-CSRF"] = token
        headers["Origin"] = url.rsplit("/api/", 1)[0]
    req = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with build_opener(ProxyHandler({})).open(req, timeout=3) as response:
        return json.loads(response.read())


def main():
    findings = scan()
    if findings:
        print(json.dumps({"status": "FAIL", "readinessFindings": findings}))
        return 1
    with tempfile.TemporaryDirectory(prefix="agentcity-separation-") as temp:
        root = Path(temp).resolve()
        app = root / "relocated" / "agent-city"
        shutil.copytree(APP, app, ignore=shutil.ignore_patterns(*EXCLUDES))
        private = root / "relocated" / "agent-city-data"
        private.mkdir()
        pointer = private / "connection.local.json"
        pointer.write_text(json.dumps({"schemaVersion": 1, "dataRoot": "."}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES and not k.startswith("AGENT_CITY_") and k != "CODEX_HOME"}
        env.update(AGENT_CITY_CONFIG=str(pointer), USERPROFILE=str(root / "home"), HOME=str(root / "home"), PYTHONDONTWRITEBYTECODE="1")
        before = hashes(app)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        capability = secrets.token_urlsafe(32)
        owner_host = 'agent-city-'+secrets.token_hex(16)+'.localhost'
        env.update(AGENT_CITY_OWNER_BOOTSTRAP=capability, AGENT_CITY_OWNER_HOST=owner_host)
        OWNER_HEADERS.update(Host=owner_host+':'+str(port), Origin='http://'+owner_host+':'+str(port))
        process = subprocess.Popen([sys.executable, "server.py", "--local-only", "--no-refresh", "--port", str(port)], cwd=app, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 12
            while True:
                try:
                    health = request(base + "/api/health")
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise AssertionError("Clean offline server did not start")
                    time.sleep(0.1)
            assert health["appId"] == "agent-city-panel"
            assert health["localOnly"] is True
            bootstrap = Request(base+'/api/owner-bootstrap',data=json.dumps({'capability':capability}).encode(),headers={**OWNER_HEADERS,'Content-Type':'application/json','X-Agent-City':'1'})
            with build_opener(ProxyHandler({})).open(bootstrap,timeout=3) as response:
                OWNER_HEADERS['Cookie']=response.headers['Set-Cookie'].split(';',1)[0]
            capability = None
            state = request(base + "/api/state")
            assert Path(state["settings"]["dataRoot"]) == private / "panel"
            assert Path(state["settings"]["skillsRoot"]) == private / "skills"
            assert (private / "skills/example/SKILL.md").is_file()
            assert not (private / "credentials").exists(), "Startup created credential files"
            assert not (private / "codex-home").exists(), "Startup created Codex config"
            assert not any(x.get("available") for k, x in state["credentialInfo"].items() if k != "kilo")
        finally:
            process.terminate()
            process.wait(timeout=10)

        # Save/reload both projects and editable skills in the same relocated package.
        code = """
import json
from pathlib import Path
from server import Store
from storage_config import load_storage
from project_library import ProjectLibrary
storage = load_storage()
store = Store(storage.panel, executable=False, local_only=True)
record = store.projects.list()[0]
record['description']['en'] = 'Synthetic persisted edit'
store.projects.save(record, store.projects.revision())
assert ProjectLibrary(storage.panel / 'projects.json').list()[0]['description']['en'] == 'Synthetic persisted edit'
assert load_storage().root == Path.cwd().parent / 'agent-city-data'
path = storage.skills / 'example/SKILL.md'
path.write_text(path.read_text('utf-8') + '\\nSynthetic saved edit.\\n', encoding='utf-8')
assert 'Synthetic saved edit.' in path.read_text('utf-8')
store.state['favorites'] = ['synthetic-provider|synthetic-model']
store.save()
assert Store(storage.panel, executable=False, local_only=True).state['favorites'] == ['synthetic-provider|synthetic-model']
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=app, env=env, capture_output=True)
        assert result.returncode == 0, "Synthetic persistence check failed"
        assert before == hashes(app), "Application files changed during use"

        # Fail closed when private directories are configured inside the app.
        pointer.write_text(json.dumps({"schemaVersion": 1, "dataRoot": str(app / "private")}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-c", "from storage_config import load_storage; load_storage()"], cwd=app, env=env, capture_output=True)
        assert result.returncode != 0 and not (app / "private").exists()
        pointer.unlink()
        result = subprocess.run([sys.executable, "-c", "from storage_config import load_storage; load_storage()"], cwd=app, env=env, capture_output=True)
        assert result.returncode != 0, "Missing explicit pointer silently used another profile"

    print(json.dumps({"status": "PASS", "checks": ["heuristic-export-scan", "relocated-offline-http-launch", "external-skills-and-data", "synthetic-project-settings-persistence", "no-app-mutations", "no-default-credentials-or-codex-writes", "reject-data-inside-app", "reject-missing-explicit-pointer"], "limitations": "Windows local candidate; heuristic scan is not exhaustive; live migration and publication not performed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
