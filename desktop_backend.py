"""Frozen backend dispatcher: never installs or opens a UI."""
import sys


def main():
    if sys.argv[1:] == ["--self-test"]:
        import json
        from pathlib import Path
        import sqlite3, ssl
        root = Path(__file__).resolve().parent
        ok = (root / "static/index.html").is_file() and (root / "published_catalog_seed.json").is_file()
        print(json.dumps({"backendBundleSelfTest":ok, "frozen":bool(getattr(sys,"frozen",False)), "serverStarted":False}))
        return 0 if ok else 2
    if len(sys.argv) >= 3 and sys.argv[1] == "--internal-script":
        script = sys.argv[2]
        sys.argv = [script, *sys.argv[3:]]
        if script == "server.py":
            import server
            server.main()
            return 0
        if script == "city.py":
            import city
            return city.main()
        return 2
    import desktop_bridge
    return desktop_bridge.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
