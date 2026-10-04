# Exact tracked public assets, never a whole source/runtime directory glob.
from pathlib import Path
import hashlib, json, os
root = Path(SPECPATH).parent
asset_manifest = json.loads(Path(os.environ["AGENT_CITY_DESKTOP_ASSET_MANIFEST"]).read_text())
assets = []
for item in asset_manifest:
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts or not (relative.parts[0] in {"static", "vendor", "demo"} or relative.as_posix() == "published_catalog_seed.json"):
        raise ValueError("asset allowlist")
    source = root / relative
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError("asset changed")
    assets.append((str(source), relative.parent.as_posix()))
a = Analysis([str(root / "desktop_backend.py")], pathex=[str(root)],
             binaries=[], datas=assets, hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=["tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AgentCityBackend",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AgentCityBackend")
# COLLECT destinations define exact allowed outputs; the package copy rejects
# extra files even if their extensions happen to look like DLLs or JSON.
allowed = ["AgentCityBackend.exe"] + ["_internal/" + entry[0].replace("\\", "/") for entry in a.binaries + a.datas]
Path(os.environ["AGENT_CITY_DESKTOP_BUNDLE_ALLOWLIST"]).write_text(json.dumps(sorted(set(allowed))))
