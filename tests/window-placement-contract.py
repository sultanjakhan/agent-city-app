"""Run the actual presentation-state policy without WinForms or a backend.

Requires the .NET 10 SDK; this contract is portable and does not accept a Windows
binary or verify native monitor/DPI event delivery.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not shutil.which("dotnet"):
        raise SystemExit("Window placement contract not run: .NET 10 SDK unavailable")
    with tempfile.TemporaryDirectory(prefix="agent-city-placement-contract-") as temporary:
        project = Path(temporary) / "WindowPlacementContract.csproj"
        project.write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>'
            '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup><ItemGroup>'
            f'<Compile Include="{ROOT / "desktop/WindowPlacement.cs"}" />'
            f'<Compile Include="{ROOT / "tests/WindowPlacementContract.cs"}" />'
            '</ItemGroup></Project>', encoding="utf-8",
        )
        subprocess.run(["dotnet", "build", str(project), "--ignore-failed-sources", "-v:minimal"], check=True)
        subprocess.run(["dotnet", str(Path(temporary) / "bin/Debug/net10.0/WindowPlacementContract.dll")], check=True)


if __name__ == "__main__":
    main()
