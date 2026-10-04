param([string]$OutputDirectory = (Join-Path ([IO.Path]::GetTempPath()) ('agent-city-copy-' + [guid]::NewGuid().ToString('N'))), [ValidateSet('Copy','Locale','Host')][string]$Contract='Copy')
$ErrorActionPreference = 'Stop'
$dotnet = (Get-Command dotnet).Source
$dotnetRoot = Split-Path $dotnet
$sdk = Get-ChildItem (Join-Path $dotnetRoot 'sdk') -Directory | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$pack = Get-ChildItem (Join-Path $dotnetRoot 'packs\Microsoft.NETCore.App.Ref') -Directory | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$ref = Get-ChildItem (Join-Path $pack.FullName 'ref') -Directory | Select-Object -First 1
$framework = $ref.Name
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$output = Join-Path $OutputDirectory 'NativeCopyContract.dll'
$references = Get-ChildItem $ref.FullName -Filter '*.dll' | ForEach-Object { '/reference:' + $_.FullName }
$compiler = Join-Path $sdk.FullName 'Roslyn\bincore\csc.dll'
$sources = @((Join-Path $PSScriptRoot '..\desktop\DesktopText.cs'))
if ($Contract -eq 'Host') {
    $generated = Join-Path $OutputDirectory 'NativeHostWiringContract.cs'
    & python (Join-Path $PSScriptRoot 'native_host_wiring_contract.py') --output $generated
    if ($LASTEXITCODE -ne 0) { throw 'Host source contract failed' }
    $sources += (Join-Path $PSScriptRoot '..\desktop\DesktopLocale.cs')
    $sources += $generated
} elseif ($Contract -eq 'Locale') {
    $sources += (Join-Path $PSScriptRoot '..\desktop\DesktopLocale.cs')
    $sources += (Join-Path $PSScriptRoot 'NativeLocaleContract.cs')
} else { $sources += (Join-Path $PSScriptRoot 'NativeCopyContract.cs') }
& $dotnet $compiler /nologo /target:exe /nullable:enable /out:$output @references @sources
if ($LASTEXITCODE -ne 0) { throw 'Pure native copy compilation failed' }
$runtime = @{runtimeOptions=@{tfm=$framework;framework=@{name='Microsoft.NETCore.App';version=$pack.Name};rollForward='LatestPatch'}} | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'NativeCopyContract.runtimeconfig.json'), $runtime)
& $dotnet $output
if ($LASTEXITCODE -ne 0) { throw 'Native copy contract failed' }
