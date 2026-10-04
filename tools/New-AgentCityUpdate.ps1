param(
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$SigningKeyPath = (Join-Path $env:LOCALAPPDATA 'Agent City/signing/release-key.dpapi')
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$key = [IO.Path]::GetFullPath($SigningKeyPath)
if (-not (Test-Path -LiteralPath $key -PathType Leaf)) { throw 'Encrypted release signing key unavailable' }
if ((Get-Item -LiteralPath $key).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Invalid signing key path' }
$privateBytes = [Security.Cryptography.ProtectedData]::Unprotect(
    [IO.File]::ReadAllBytes($key), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
$rsa = [Security.Cryptography.RSA]::Create()
try {
    $read = 0
    $rsa.ImportPkcs8PrivateKey($privateBytes, [ref]$read)
    $trust = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '../desktop/UpdateTrust.cs'))
    $pinned = [regex]::Match($trust, '-----BEGIN PUBLIC KEY-----[\s\S]*?-----END PUBLIC KEY-----').Value
    if ($rsa.ExportSubjectPublicKeyInfoPem().Replace("`r", '').Trim() -ne $pinned.Replace("`r", '').Trim()) {
        throw 'Signing key does not match the application update key'
    }
    & python -X utf8 (Join-Path $PSScriptRoot 'pack_update.py') --candidate $Candidate --output $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Release package validation failed' }
    $manifest = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'latest.json'
    $signature = $rsa.SignData([IO.File]::ReadAllBytes($manifest),
        [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    [IO.File]::WriteAllText(($manifest + '.sig'), [Convert]::ToBase64String($signature), [Text.UTF8Encoding]::new($false))
    'Update package signed; private signing key remains outside the repository.'
} finally {
    [Array]::Clear($privateBytes, 0, $privateBytes.Length)
    $rsa.Dispose()
}
