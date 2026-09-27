param([switch]$Publish)

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
$programAddress = & $keygen pubkey $programKey
if ($LASTEXITCODE -ne 0 -or $programAddress -cne $public.program_id) { throw 'Existing program key has another public address.' }
$payerAddress = & $keygen pubkey $payerKey
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
# Conservatively cover a program, its upload buffer, setup and initial task fees.
$minimum = [long]$rent * 2 + 50000000L
$review = [ordered]@{
    network = 'devnet'
    rpc_url = $rpcUrl
    program_id = $public.program_id
    config_authority = $public.gateway_pubkey
    treasury = $public.treasury
    binary_sha256 = $binaryHash
    binary_bytes = $manifest.binary_bytes
    program_already_exists = ($null -ne $programAccount.value)
    available_lamports = $balance.value
    suggested_minimum_lamports = $minimum
}
$review | ConvertTo-Json
if (-not $Publish) { Write-Host 'Review only. No transaction was submitted.'; exit 0 }
if ($programAccount.value) { throw 'The program already exists. Inspect the deployed bytes before considering an upgrade.' }
if ([long]$balance.value -lt $minimum) { throw 'Insufficient Devnet funds. No deployment was submitted.' }

# A failed CLI upload can emit a recovery seed. Keep its complete output private.
$privateLog = Join-Path $state 'deploy.private.stdout.log'
$privateErrorLog = Join-Path $state 'deploy.private.stderr.log'
$env:PATH = $agaveBin + ';' + $env:PATH
$deployArguments = @('--url', $rpcUrl, '--keypair', ('"' + $payerKey + '"'), '--output', 'json',
    'program', 'deploy', ('"' + $binary + '"'), '--program-id', ('"' + $programKey + '"'),
    '--upgrade-authority', ('"' + $payerKey + '"'), '--max-len', [string]$manifest.binary_bytes, '--max-sign-attempts', '5')
$process = Start-Process -FilePath $solana -ArgumentList $deployArguments -WindowStyle Hidden `
    -RedirectStandardOutput $privateLog -RedirectStandardError $privateErrorLog -PassThru -Wait
if ($process.ExitCode -ne 0) { throw 'Deployment did not finish successfully. Inspect the ignored private deploy logs locally before retrying.' }
$confirmed = Invoke-DevnetRpc 'getAccountInfo' @($public.program_id, @{ encoding = 'base64'; commitment = 'confirmed' })
if (-not $confirmed.value.executable) { throw 'CLI returned, but the executable program is not confirmed. Inspect the existing deployment before retrying.' }
Write-Host ('Executable program confirmed on Devnet: ' + $public.program_id)
Write-Host 'Read back and initialize the reviewed program with scripts/devnet.py initialize.'
