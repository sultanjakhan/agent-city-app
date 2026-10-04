"""Offline desktop build: fresh outputs/staging, exact allowlist, atomic publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
HOST_FILES = {
    "AgentCity.exe", "AgentCity.dll", "AgentCity.deps.json", "AgentCity.runtimeconfig.json",
    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
    "Microsoft.Web.WebView2.Core.xml", "Microsoft.Web.WebView2.WinForms.xml",
    "runtimes/win-x64/native/WebView2Loader.dll", "runtimes/win-x86/native/WebView2Loader.dll",
    "runtimes/win-arm64/native/WebView2Loader.dll",
}
HOST_IGNORED = {"AgentCity.pdb", "Microsoft.Web.WebView2.Wpf.dll", "Microsoft.Web.WebView2.Wpf.xml"}


def safe_tree(directory):
    pending = [directory]
    found = set()
    while pending:
        parent = pending.pop()
        for path in parent.iterdir():
            attributes = path.lstat()
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 0x400:
                raise ValueError("reparse build entry")
            if path.is_dir():pending.append(path)
            elif path.is_file():found.add(path.relative_to(directory).as_posix())
            else:raise ValueError("nonregular build entry")
    return found


def copy_allowed(source, target, allowed, ignored=()):
    actual = safe_tree(source)
    if actual - set(ignored) != set(allowed):
        raise ValueError("unexpected or missing build output")
    copied = set()
    for relative in sorted(allowed):
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("invalid output allowlist")
        destination = target / relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source / relative, destination)
        copied.add(relative)
    return copied


def stage_package(build, run, commit, host, backend, backend_allowed, license_files):
    identity = uuid.uuid4().hex
    staging = build / (".staging-" + identity)
    destination = build / ("candidate-" + commit[:8] + "-" + identity)
    staging.mkdir() # Must be new/empty. Never clean, reuse or delete an old candidate.
    copied = copy_allowed(host, staging, HOST_FILES, HOST_IGNORED)
    copied.update("backend/" + name for name in copy_allowed(backend, staging / "backend", backend_allowed))
    shutil.copy2(ROOT / "DESKTOP-CANDIDATE.md", staging / "DESKTOP-CANDIDATE.md")
    copied.add("DESKTOP-CANDIDATE.md")
    license_path = ROOT / "LICENSE"
    if license_path.is_symlink() or not license_path.is_file():
        raise ValueError("application license unavailable")
    license_target = staging / "licenses/AgentCity-LICENSE.txt"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(license_path, license_target)
    copied.add("licenses/AgentCity-LICENSE.txt")
    for relative, source in license_files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not relative.startswith("licenses/"):
            raise ValueError("license allowlist")
        target = staging / relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        copied.add(relative)
    if safe_tree(staging) != copied:raise ValueError("staging allowlist changed")
    files = [{"path":name,"sha256":hashlib.sha256((staging/name).read_bytes()).hexdigest(),"bytes":(staging/name).stat().st_size} for name in sorted(copied)]
    version = json.loads((ROOT / "package.json").read_text())["version"]
    manifest = {"status":"QA_ONLY_NOT_INSTALLED", "sourceCommit":commit,
                "applicationSourceVersion":version,
                "artifactVersion":version+"-desktop."+commit[:8], "runtime":"normal by default; --local-only for isolated QA",
                "files":files, "allowlist":sorted(copied), "installed":False, "releaseAccepted":False}
    (staging/"build-manifest.json").write_text(json.dumps(manifest,indent=2))
    if safe_tree(staging) != copied | {"build-manifest.json"}:raise ValueError("unexpected staged file")
    staging.rename(destination) # Same-filesystem atomic publish to a unique absent destination.
    return destination, manifest


def main():
    parser = argparse.ArgumentParser();parser.add_argument("--build-root",type=Path,required=True)
    raw_build = parser.parse_args().build_root.absolute()
    for path in [raw_build, *raw_build.parents]:
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):raise ValueError("reparse build root")
    build = raw_build.resolve()
    if build == ROOT or build in ROOT.parents or len(build.parts)<3:raise ValueError("unsafe build root")
    marker = build / ".agentcity-desktop-build-root"
    if build.exists() and any(build.iterdir()) and not marker.is_file():raise ValueError("unowned nonempty build root")
    build.mkdir(parents=True,exist_ok=True)
    if marker.exists():
        if marker.is_symlink() or marker.read_text() != "Agent City isolated build outputs only\n":raise ValueError("invalid ownership marker")
    else:marker.write_text("Agent City isolated build outputs only\n")
    if not (build/"python-tools/PyInstaller").is_dir():raise ValueError("offline build tools not prepared")
    def git(*args):return subprocess.check_output(["git","-c","safe.directory="+str(ROOT),"-c","core.fsmonitor=false","-C",str(ROOT),*args])
    if git("status","--porcelain").strip():raise ValueError("exact clean commit required")
    commit=git("rev-parse","HEAD").decode().strip()
    run=build/("run-"+uuid.uuid4().hex);run.mkdir()
    asset_names=git("ls-files","-z","static","vendor","demo","published_catalog_seed.json").decode().split("\0")
    assets=[{"path":name,"sha256":hashlib.sha256((ROOT/name).read_bytes()).hexdigest()} for name in asset_names if name]
    (run/"assets.json").write_text(json.dumps(assets))
    env=dict(os.environ)
    env.update(DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",DOTNET_CLI_TELEMETRY_OPTOUT="1",
               DOTNET_GENERATE_ASPNET_CERTIFICATE="false",DOTNET_CLI_HOME=str(build/"dotnet-home"),
               PYTHONPATH=str(build/"python-tools"),AGENT_CITY_DESKTOP_ASSET_MANIFEST=str(run/"assets.json"),
               AGENT_CITY_DESKTOP_BUNDLE_ALLOWLIST=str(run/"bundle-allowlist.json"))
    project = str(ROOT / "desktop/AgentCity.Desktop.csproj")
    # Resolve locked dependencies from the explicitly owned build root. A clean
    # public checkout must not depend on another checkout's obj/assets or layout.
    package_path = "-p:RestorePackagesPath=" + str(build / "nuget-packages")
    package_source = str(build / "nuget-packages/microsoft.web.webview2/1.0.3537.50")
    subprocess.run(["dotnet", "restore", project, "--locked-mode", "--source", package_source,
                    package_path], env=env, check=True)
    subprocess.run(["dotnet","build",project,"--no-restore",package_path,"-c","Release","-o",str(run/"host")],env=env,check=True)
    subprocess.run([sys.executable,"-m","PyInstaller",str(ROOT/"desktop/AgentCityBackend.spec"),"--distpath",str(run/"frozen"),"--workpath",str(run/"pyinstaller-work"),"--noconfirm"],env=env,check=True)
    if git("status","--porcelain").strip() or git("rev-parse","HEAD").decode().strip()!=commit:raise ValueError("source changed during build")
    if any(hashlib.sha256((ROOT/a["path"]).read_bytes()).hexdigest()!=a["sha256"] for a in assets):raise ValueError("asset changed during build")
    licenses={}
    sdk=build/"nuget-packages/microsoft.web.webview2/1.0.3537.50"
    for name in ("LICENSE.txt","NOTICE.txt"):
        path=sdk/name
        if not path.is_file() or path.is_symlink():raise ValueError("SDK license unavailable")
        licenses["licenses/WebView2-"+name]=path
    dependency_lock=json.loads((ROOT/"desktop/build-dependencies.json").read_text())
    for dependency in dependency_lock:
        wheel=build/"dependencies"/dependency["wheel"]
        if hashlib.sha256(wheel.read_bytes()).hexdigest()!=dependency["sha256"]:raise ValueError("build dependency changed")
        for relative, expected in dependency["licenseFiles"].items():
            source=build/"python-tools"/relative
            if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError("dependency license changed")
            licenses["licenses/"+relative]=source
    python_license=Path(sys.base_prefix)/"LICENSE.txt"
    if python_license.is_file():licenses["licenses/Python-LICENSE.txt"]=python_license
    allowed=json.loads((run/"bundle-allowlist.json").read_text())
    package,manifest=stage_package(build,run,commit,run/"host",run/"frozen/AgentCityBackend",allowed,licenses)
    (run/"result.json").write_text(json.dumps({"candidate":str(package),"sourceCommit":commit}))
    print(json.dumps({"candidate":str(package),"sourceCommit":commit,"packagedFiles":len(manifest["files"]),"bytes":sum(f["bytes"] for f in manifest["files"]),"installed":False}))


if __name__=="__main__":main()
