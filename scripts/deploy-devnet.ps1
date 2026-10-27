param(
    [switch]$Publish,
    [switch]$Upgrade
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$state = Join-Path $projectRoot '.aperture\demo\devnet'
$public = Get-Content -LiteralPath (Join-Path $state 'public.json') -Raw | ConvertFrom-Json
$manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'target\deploy\build-manifest.json') -Raw | ConvertFrom-Json
$rpcUrl = 'https://api.devnet.solana.com'
if ($public.network -cne 'devnet' -or $public.rpc_url -cne $rpcUrl) { throw 'Official Devnet configuration required.' }
$binary = Join-Path $projectRoot 'target\deploy\aperture_gateway.so'
$binaryHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
if (($binaryHash -cne $manifest.binary_sha256) -or
    ((Get-Item -LiteralPath $binary).Length -ne $manifest.binary_bytes) -or
    ($manifest.program_id -cne $public.program_id) -or ($manifest.config_authority -cne $public.gateway_pubkey)) {
    throw 'The binary, authority or program address differs from the reviewed manifest.'
}
$agaveBin = Join-Path $projectRoot '.aperture\tools\agave-4.3.0\solana-release\bin'
$solana = Join-Path $agaveBin 'solana.exe'
$keygen = Join-Path $agaveBin 'solana-keygen.exe'
$programKey = Join-Path $projectRoot '.aperture\devnet\program.json'
$payerKey = Join-Path $projectRoot '.aperture\demo\gateway.keypair.json'
$cliConfigFile = Join-Path ([IO.Path]::GetTempPath()) ('aperture-solana-cli-' + [guid]::NewGuid().ToString('N') + '.json')
$cliSettings = [ordered]@{
    json_rpc_url = $rpcUrl
    websocket_url = ''
    keypair_path = $payerKey
    address_labels = @{}
    commitment = 'confirmed'
}

try {
    [IO.File]::WriteAllText($cliConfigFile, ($cliSettings | ConvertTo-Json -Depth 5 -Compress), [Text.UTF8Encoding]::new($false))

$programAddress = & $keygen 'pubkey' '--config' $cliConfigFile $programKey
if ($LASTEXITCODE -ne 0 -or $programAddress -cne $public.program_id) { throw 'Existing program key has another public address.' }
$payerAddress = & $keygen 'pubkey' '--config' $cliConfigFile $payerKey
if ($LASTEXITCODE -ne 0 -or $payerAddress -cne $public.gateway_pubkey) { throw 'Development signer differs from the pinned authority.' }

function Invoke-DevnetRpc([string]$Method, [object[]]$Params) {
    $body = @{ jsonrpc = '2.0'; id = 1; method = $Method; params = @($Params) } | ConvertTo-Json -Depth 8 -Compress
    $response = Invoke-RestMethod -Uri $rpcUrl -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 20
    if ($response.error) { throw ('Devnet RPC failed: ' + $response.error.message) }
    return $response.result
}

$programAccount = Invoke-DevnetRpc 'getAccountInfo' @($public.program_id, @{ encoding = 'base64'; commitment = 'confirmed' })
$balance = Invoke-DevnetRpc 'getBalance' @($public.gateway_pubkey, @{ commitment = 'confirmed' })
$rent = Invoke-DevnetRpc 'getMinimumBalanceForRentExemption' @([long]$manifest.binary_bytes + 128)
$programExists = $null -ne $programAccount.value
if ($programExists -and -not $programAccount.value.executable) {
    throw 'The target address exists but is not an executable program. No deployment was submitted.'
}
if ($Upgrade -and -not $programExists) {
    throw 'Upgrade mode requires an existing executable program. No deployment was submitted.'
}

$deployedAuthority = $null
if ($programExists) {
    $programInfo = & $solana '--config' $cliConfigFile '--url' $rpcUrl 'program' 'show' $public.program_id 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'The existing program authority could not be read from Devnet. No deployment was submitted.'
    }
    $authorityMatch = [regex]::Match(($programInfo -join "`n"), '(?m)^\s*Authority:\s*(?<authority>\S+)\s*$')
    if (-not $authorityMatch.Success) {
        throw 'The CLI output did not identify an upgrade authority. No deployment was submitted.'
    }
    $deployedAuthority = $authorityMatch.Groups['authority'].Value
}
$signerIsUpgradeAuthority = $programExists -and ($deployedAuthority -ceq $payerAddress)

# Conservatively cover a program, its upload buffer, setup and initial task fees.
$minimum = [long]$rent * 2 + 50000000L
$review = [ordered]@{
    network = 'devnet'
    rpc_url = $rpcUrl
    deployment_mode = if ($programExists) { if ($Upgrade) { 'upgrade' } else { 'existing-program' } } else { 'new-program' }
    program_id = $public.program_id
    config_authority = $public.gateway_pubkey
    deployed_upgrade_authority = $deployedAuthority
    signer_is_upgrade_authority = $signerIsUpgradeAuthority
    treasury = $public.treasury
    binary_sha256 = $binaryHash
    binary_bytes = $manifest.binary_bytes
    program_already_exists = $programExists
    available_lamports = $balance.value
    suggested_minimum_lamports = $minimum
}
$review | ConvertTo-Json
if (-not $Publish) {
    if ($programExists -and -not $Upgrade) {
        Write-Host 'Review only. This address is already deployed; rerun with -Upgrade to review the explicit upgrade path.'
    } elseif ($programExists -and -not $signerIsUpgradeAuthority) {
        Write-Host 'Review only. The configured signer is not the current program upgrade authority.'
    } else {
        Write-Host 'Review only. No transaction was submitted.'
    }
    return
}
if ($programExists -and -not $Upgrade) { throw 'The program already exists. Pass -Upgrade explicitly after reviewing the Devnet authority and build.' }
if ($programExists -and -not $signerIsUpgradeAuthority) { throw 'The configured signer is not the existing program upgrade authority. No transaction was submitted.' }
if ([long]$balance.value -lt $minimum) { throw 'Insufficient Devnet funds. No deployment was submitted.' }

# A failed CLI upload can emit a recovery seed. Keep its complete output private.
$privateLog = Join-Path $state 'deploy.private.stdout.log'
$privateErrorLog = Join-Path $state 'deploy.private.stderr.log'
$env:PATH = $agaveBin + ';' + $env:PATH
$deployArguments = @('--config', $cliConfigFile, '--url', $rpcUrl, '--keypair', ('"' + $payerKey + '"'), '--output', 'json',
    'program', 'deploy', ('"' + $binary + '"'), '--program-id', ('"' + $programKey + '"'),
    '--upgrade-authority', ('"' + $payerKey + '"'), '--max-len', [string]$manifest.binary_bytes, '--max-sign-attempts', '5')
$process = Start-Process -FilePath $solana -ArgumentList $deployArguments -WindowStyle Hidden `
    -RedirectStandardOutput $privateLog -RedirectStandardError $privateErrorLog -PassThru -Wait
if ($process.ExitCode -ne 0) { throw 'Deployment did not finish successfully. Inspect the ignored private deploy logs locally before retrying.' }
$confirmed = Invoke-DevnetRpc 'getAccountInfo' @($public.program_id, @{ encoding = 'base64'; commitment = 'confirmed' })
if (-not $confirmed.value.executable) { throw 'CLI returned, but the executable program is not confirmed. Inspect the existing deployment before retrying.' }
Write-Host ('Executable program confirmed on Devnet: ' + $public.program_id)
Write-Host 'Read back and initialize the reviewed program with scripts/devnet.py initialize.'
} finally {
    if (Test-Path -LiteralPath $cliConfigFile) {
        Remove-Item -LiteralPath $cliConfigFile -Force
    }
}
