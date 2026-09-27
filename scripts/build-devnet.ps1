param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[1-9A-HJ-NP-Za-km-z]{32,44}$')]
    [string]$ConfigAuthority
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw 'Install Microsoft C++ Build Tools and a Windows SDK first.'
}
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'A complete Microsoft C++ toolchain was not found.' }
& (Join-Path $vsRoot 'Common7\Tools\Launch-VsDevShell.ps1') -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
if (-not (Get-Command link.exe -ErrorAction SilentlyContinue)) { throw 'Microsoft linker is unavailable.' }

$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$agaveBin = Join-Path $projectRoot '.aperture\tools\agave-4.3.0\solana-release\bin'
$sbf = Join-Path $agaveBin 'cargo-build-sbf.exe'
if (-not (Test-Path -LiteralPath $sbf)) {
    $installed = Get-Command cargo-build-sbf.exe -ErrorAction SilentlyContinue
    if (-not $installed) { throw 'Install the Agave 4.3.0 build tools first.' }
    $sbf = $installed.Source
    $agaveBin = Split-Path -Parent $sbf
}
if (-not (Test-Path -LiteralPath $cargo)) { throw 'Install Rust for x86_64-pc-windows-msvc first.' }

$env:APERTURE_CONFIG_AUTHORITY = $ConfigAuthority
$env:PATH = (Split-Path -Parent $cargo) + ';' + $agaveBin + ';' + $env:PATH
Push-Location -LiteralPath $projectRoot
try {
    Write-Host ('Building with protocol authority ' + $ConfigAuthority)
    & $cargo check --locked --manifest-path programs/Cargo.toml
    if ($LASTEXITCODE -ne 0) { throw 'Native Rust compilation failed.' }
    & $sbf --arch v3 --manifest-path programs/Cargo.toml --sbf-out-dir target/deploy --jobs 4
    if ($LASTEXITCODE -ne 0) { throw 'Solana program compilation failed.' }
    $binary = Join-Path $projectRoot 'target\deploy\aperture_gateway.so'
    $manifest = [ordered]@{
        program_id = 'A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ'
        config_authority = $ConfigAuthority
        binary_sha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
        binary_bytes = (Get-Item -LiteralPath $binary).Length
        built_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    $manifest | ConvertTo-Json | Set-Content 'target/deploy/build-manifest.json' -Encoding utf8
    $manifest | ConvertTo-Json
    Write-Host 'Program built. Review the manifest before deploying to Devnet.'
} finally {
    Pop-Location
}
