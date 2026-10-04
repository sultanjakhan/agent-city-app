"""Focused updater contract: compile the two native update units in isolation and
check the high risk boundaries that a source build cannot exercise on CI.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    updater = (ROOT / "desktop/AppUpdater.cs").read_text(encoding="utf-8")
    installer = (ROOT / "desktop/UpdateInstall.cs").read_text(encoding="utf-8")
    required = [
        "CheckAndStageAsync", "StartPeriodic", "VerifyDetachedManifest",
        "ExtractAndVerify", "ZipFile.OpenRead", "WaitForOwnerExit",
        "PrepareHelperBundle", "Directory.Move(install, rollback)",
        "UpdateTrust.PublicKeyPem",  # wiring contract is checked by the host source
    ]
    source = updater + installer
    for token in required[:-1]:
        if token not in source:
            raise AssertionError(f"missing updater boundary: {token}")
    if "Process.Kill" in source or ".Kill(" in source:
        raise AssertionError("updater must never force-kill a process")
    if "RSASignaturePadding.Pkcs1" not in installer or "HashAlgorithmName.SHA256" not in installer:
        raise AssertionError("detached RSA/SHA256 verification missing")
    if "StringComparer.OrdinalIgnoreCase" not in source:
        raise AssertionError("case-collision protection missing")
    host = (ROOT / "desktop/Program.cs").read_text(encoding="utf-8")
    if "RunHelper(args[1], UpdateTrust.PublicKeyPem)" not in host:
        raise AssertionError("helper must receive the pinned production key")

    # Compile only the updater units. The full desktop tree may be edited by the
    # host agent at the same time, while these units have no UI/package dependency.
    with tempfile.TemporaryDirectory(prefix="agent-city-update-compile-") as temp:
        project = Path(temp) / "UpdateCompile.csproj"
        project.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">'
            '<PropertyGroup><TargetFramework>net10.0</TargetFramework>'
            '<Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>'
            f'<ItemGroup><Compile Include="{ROOT / "desktop/UpdateInstall.cs"}" />'
            f'<Compile Include="{ROOT / "desktop/AppUpdater.cs"}" /></ItemGroup></Project>',
            encoding="utf-8",
        )
        result = subprocess.run(
            ["dotnet", "build", str(project), "--ignore-failed-sources", "-v:minimal"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
    print("PASS native updater contract: isolated net10 compile, host wiring and static safety guards")


if __name__ == "__main__":
    main()
