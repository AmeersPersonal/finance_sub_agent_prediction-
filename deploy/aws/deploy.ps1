<#
.SYNOPSIS
  Build and deploy Market Moves to AWS with SAM: the API as a Lambda container
  image, the frontend on S3 + CloudFront at your own domain (template.yaml at the
  repo root).

.DESCRIPTION
  Steps: check tools and AWS credentials -> load settings -> TLS certificate for
  the domain -> sam build -> sam deploy -> (optional) database migrations ->
  npm run build -> sync to S3 -> invalidate CloudFront -> print what to do next.

  Settings come from backend\.env (override the path with -EnvFile) and from
  environment variables of the same names, which win. Values are passed to the
  function's environment and are never printed. Missing DATABASE_URL and
  GEMINI_API_KEY are asked for with a masked prompt.

  SNOWFLAKE_PRIVATE_KEY_FILE is a path on this machine. The script reads that
  file and ships its contents (the function writes it to /tmp at run time), so
  Snowflake retrieval works on AWS without the file being on a disk there.

  Values may not contain double quotes.

.EXAMPLE
  .\deploy\aws\deploy.ps1 -RunMigrations      # first deploy
  .\deploy\aws\deploy.ps1                     # later deploys
  .\deploy\aws\deploy.ps1 -SkipBackend        # frontend only
  .\deploy\aws\deploy.ps1 -DomainName ''      # no custom domain (the *.cloudfront.net name)
#>
[CmdletBinding()]
param(
  [string]$StackName = 'market-moves',
  [string]$Region = '',
  [string]$DomainName = 'marketmoves.nyc',
  [string]$EnvFile = '',
  [switch]$RunMigrations,
  # Run the function behind a NAT gateway with one Elastic IP, for a database with an IP allow list.
  [switch]$StaticIp,
  [switch]$SkipBackend,
  [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $EnvFile) { $EnvFile = Join-Path $root 'backend\.env' }
$CertRegion = 'us-east-1'  # CloudFront only accepts certificates from this region
if ($DomainName -and $DomainName -notmatch '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$') {
  Write-Host "ERROR: -DomainName must be a bare hostname such as marketmoves.nyc (got '$DomainName'), not a URL." -ForegroundColor Red
  Write-Host "Using Vercel for the frontend? Pass -DomainName '' (the domain belongs to Vercel, not this stack)." -ForegroundColor Yellow
  exit 1
}

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }
function Need($command, $hint) {
  if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { Fail "'$command' not found. $hint" }
}
function Run {
  # Run a native command and stop if it fails.
  param([string]$File, [string[]]$Arguments)
  & $File @Arguments
  if ($LASTEXITCODE -ne 0) { Fail "$File $($Arguments[0]) failed (exit code $LASTEXITCODE)." }
}
function Capture {
  # Run a native command, return its trimmed output or $null on failure (stderr is expected noise).
  param([string]$File, [string[]]$Arguments)
  $ErrorActionPreference = 'Continue'
  $text = & $File @Arguments 2>$null
  $code = $LASTEXITCODE
  $ErrorActionPreference = 'Stop'
  if ($code -ne 0 -or $null -eq $text) { return $null }
  return ("$($text -join "`n")").Trim()
}

# --- settings -------------------------------------------------------------------

function Read-DotEnv([string]$path) {
  $map = @{}
  if (-not (Test-Path -LiteralPath $path)) { return $map }
  foreach ($line in Get-Content -LiteralPath $path) {
    $text = $line.Trim()
    if (-not $text -or $text.StartsWith('#')) { continue }
    if ($text.StartsWith('export ')) { $text = $text.Substring(7).Trim() }
    $i = $text.IndexOf('=')
    if ($i -lt 1) { continue }
    $key = $text.Substring(0, $i).Trim()
    $value = $text.Substring($i + 1).Trim()
    if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    elseif ($value -match '\s#') { $value = ($value -split '\s#', 2)[0].Trim() }
    $map[$key] = $value
  }
  return $map
}
$dotenv = Read-DotEnv $EnvFile
function Setting([string]$name) {
  $fromEnvironment = [Environment]::GetEnvironmentVariable($name)
  if ($fromEnvironment) { return $fromEnvironment }
  if ($dotenv.ContainsKey($name)) { return $dotenv[$name] }
  return ''
}
function Ask-Secret([string]$name) {
  $secure = Read-Host -AsSecureString $name
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

# CloudFormation parameter -> the environment variable it carries.
$parameterSources = [ordered]@{
  DatabaseUrl = 'DATABASE_URL'; GeminiApiKey = 'GEMINI_API_KEY'; GeminiModel = 'GEMINI_MODEL'
  GeminiModelStrong = 'GEMINI_MODEL_STRONG'; JobSigningKey = 'JOB_SIGNING_KEY'
  OAuthClientId = 'OAUTH_CLIENT_ID'; OAuthClientSecret = 'OAUTH_CLIENT_SECRET'
  OAuthRedirectUri = 'OAUTH_REDIRECT_URI'
  RagBackend = 'RAG_BACKEND'; SnowflakeAccount = 'SNOWFLAKE_ACCOUNT'; SnowflakeUser = 'SNOWFLAKE_USER'
  SnowflakeRole = 'SNOWFLAKE_ROLE'; SnowflakeWarehouse = 'SNOWFLAKE_WAREHOUSE'
  SnowflakeDatabase = 'SNOWFLAKE_DATABASE'; SnowflakeSchema = 'SNOWFLAKE_SCHEMA'
  SnowflakeEmbedModel = 'SNOWFLAKE_EMBED_MODEL'; SnowflakePrivateKeyPassphrase = 'SNOWFLAKE_PRIVATE_KEY_PASSPHRASE'
  SecUserAgent = 'SEC_USER_AGENT'; AltLlmBaseUrl = 'ALT_LLM_BASE_URL'; AltLlmModel = 'ALT_LLM_MODEL'
  AltLlmApiKey = 'ALT_LLM_API_KEY'; LiveFeed = 'LIVE_FEED'; FinnhubApiKey = 'FINNHUB_API_KEY'
  PredictionsPerHour = 'API_PREDICTIONS_PER_HOUR'
}

# --- tools and credentials ------------------------------------------------------

Step 'Checking tools and AWS credentials'
Need 'aws' 'Install the AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html'
if (-not $SkipBackend) {
  Need 'sam' 'Install the AWS SAM CLI: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html  (or: winget install Amazon.SAM-CLI)'
  Need 'docker' 'Install and start Docker Desktop: SAM builds the Lambda container image with it.'
  if ($null -eq (Capture 'docker' @('info', '--format', '{{.ServerVersion}}'))) {
    Fail 'Docker is installed but not running. Start Docker Desktop and retry.'
  }
}
if (-not $SkipFrontend) { Need 'npm' 'Install Node.js 20+: https://nodejs.org' }

$regionArgs = @()
if ($Region) { $regionArgs = @('--region', $Region) }
$arn = Capture 'aws' (@('sts', 'get-caller-identity', '--query', 'Arn', '--output', 'text') + $regionArgs)
if (-not $arn) { Fail "AWS credentials aren't usable. Run 'aws configure' or 'aws sso login'." }
Write-Host "AWS identity $arn"
if (-not $Region) {
  $Region = Capture 'aws' @('configure', 'get', 'region')
  if (-not $Region) { Fail "No region. Pass -Region (for example -Region us-east-1) or run 'aws configure'." }
  $regionArgs = @('--region', $Region)
}
Write-Host "Stack '$StackName' in $Region"
if (Test-Path -LiteralPath $EnvFile) { Write-Host "Settings from $EnvFile (values are not shown)" }
else { Write-Host "No $EnvFile; using environment variables and prompts only." }

# --- domain certificate ---------------------------------------------------------

$certificateArn = ''
$hostedZoneId = ''
if ($DomainName -and -not $SkipBackend) {
  Step "TLS certificate and DNS for $DomainName"
  $zone = Capture 'aws' @('route53', 'list-hosted-zones-by-name', '--dns-name', $DomainName, '--max-items', '1',
      '--query', "HostedZones[?Name=='$DomainName.'].Id | [0]", '--output', 'text')
  if ($zone -and $zone -ne 'None') { $hostedZoneId = $zone -replace '^/hostedzone/', '' }
  if ($hostedZoneId) { Write-Host "Route 53 hosted zone $hostedZoneId" }
  else { Write-Host "No Route 53 hosted zone for $DomainName; DNS records will need adding by hand." }

  foreach ($status in 'ISSUED', 'PENDING_VALIDATION') {
    $found = Capture 'aws' @('acm', 'list-certificates', '--region', $CertRegion, '--certificate-statuses', $status,
        '--query', "CertificateSummaryList[?DomainName=='$DomainName'].CertificateArn | [0]", '--output', 'text')
    if ($found -and $found -ne 'None') { $certificateArn = $found; break }
  }
  if (-not $certificateArn) {
    Write-Host "Requesting an ACM certificate in $CertRegion"
    $certificateArn = Capture 'aws' @('acm', 'request-certificate', '--region', $CertRegion, '--domain-name', $DomainName,
        '--validation-method', 'DNS', '--query', 'CertificateArn', '--output', 'text')
    if (-not $certificateArn) { Fail 'Could not request the certificate (needs acm:RequestCertificate).' }
  }
  $state = Capture 'aws' @('acm', 'describe-certificate', '--region', $CertRegion, '--certificate-arn', $certificateArn,
      '--query', 'Certificate.Status', '--output', 'text')
  if ($state -ne 'ISSUED') {
    $name = $null; $value = $null
    for ($try = 0; $try -lt 12 -and -not $name; $try++) {
      $name = Capture 'aws' @('acm', 'describe-certificate', '--region', $CertRegion, '--certificate-arn', $certificateArn,
          '--query', 'Certificate.DomainValidationOptions[0].ResourceRecord.Name', '--output', 'text')
      if ($name -eq 'None') { $name = $null; Start-Sleep -Seconds 5 }
    }
    if (-not $name) { Fail 'ACM has not produced the DNS validation record yet. Wait a minute and rerun.' }
    $value = Capture 'aws' @('acm', 'describe-certificate', '--region', $CertRegion, '--certificate-arn', $certificateArn,
        '--query', 'Certificate.DomainValidationOptions[0].ResourceRecord.Value', '--output', 'text')
    if ($hostedZoneId) {
      $batch = @{ Changes = @(@{ Action = 'UPSERT'; ResourceRecordSet = @{
              Name = $name; Type = 'CNAME'; TTL = 300; ResourceRecords = @(@{ Value = $value }) } }) } | ConvertTo-Json -Depth 6
      $file = New-TemporaryFile
      try {
        Set-Content -LiteralPath $file.FullName -Value $batch -Encoding ascii
        Run 'aws' @('route53', 'change-resource-record-sets', '--hosted-zone-id', $hostedZoneId,
            '--change-batch', "file://$($file.FullName)", '--output', 'text', '--query', 'ChangeInfo.Status')
      }
      finally { Remove-Item -LiteralPath $file.FullName -ErrorAction SilentlyContinue }
      Write-Host 'Waiting for the certificate to validate (usually a few minutes)...'
      Run 'aws' @('acm', 'wait', 'certificate-validated', '--region', $CertRegion, '--certificate-arn', $certificateArn)
    }
    else {
      Write-Host "`nAdd this DNS record at your DNS provider for $DomainName, then run this script again:" -ForegroundColor Yellow
      Write-Host "  Type:  CNAME"
      Write-Host "  Name:  $name"
      Write-Host "  Value: $value"
      exit 2
    }
  }
  Write-Host "Certificate ready: $certificateArn"
}

# --- backend --------------------------------------------------------------------

$databaseUrl = ''
if (-not $SkipBackend) {
  Step 'Reading settings'
  $values = [ordered]@{}
  foreach ($parameter in $parameterSources.Keys) { $values[$parameter] = Setting $parameterSources[$parameter] }
  if (-not $values['DatabaseUrl']) { $values['DatabaseUrl'] = Ask-Secret 'DATABASE_URL (PostgreSQL URI)' }
  if (-not $values['GeminiApiKey']) { $values['GeminiApiKey'] = Ask-Secret 'GEMINI_API_KEY' }
  if (-not $values['DatabaseUrl']) { Fail 'DATABASE_URL is required.' }
  if (-not $values['GeminiApiKey']) { Fail 'GEMINI_API_KEY is required.' }
  if ($values['OAuthClientId'] -and -not $values['OAuthClientSecret']) { Fail 'OAUTH_CLIENT_ID is set without OAUTH_CLIENT_SECRET.' }
  $databaseUrl = $values['DatabaseUrl']

  if (-not $values['JobSigningKey']) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $values['JobSigningKey'] = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  }

  # The Snowflake key: .env holds a path on this machine, so ship the file's contents.
  $keyPath = Setting 'SNOWFLAKE_PRIVATE_KEY_FILE'
  $values['SnowflakePrivateKeyB64'] = ''
  if ($keyPath) {
    $expanded = [Environment]::ExpandEnvironmentVariables($keyPath)
    if ($expanded.StartsWith('~')) { $expanded = Join-Path $HOME $expanded.Substring(1).TrimStart('/', '\') }
    $candidates = @($expanded, (Join-Path $root "backend\$expanded"), (Join-Path (Split-Path $EnvFile) $expanded))
    $resolved = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ($resolved) {
      $values['SnowflakePrivateKeyB64'] = [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolved))
      Write-Host "Snowflake private key: read $(Split-Path $resolved -Leaf) ($($values['SnowflakePrivateKeyB64'].Length) base64 characters)"
    }
    elseif ($values['RagBackend'] -eq 'snowflake') {
      Fail 'SNOWFLAKE_PRIVATE_KEY_FILE points to a file that does not exist on this machine, so AWS would not have it. Fix the path first.'
    }
    else { Write-Host 'SNOWFLAKE_PRIVATE_KEY_FILE not found here; skipping it (RAG_BACKEND is not snowflake).' }
  }
  elseif ($values['RagBackend'] -eq 'snowflake') { Fail 'RAG_BACKEND=snowflake needs SNOWFLAKE_PRIVATE_KEY_FILE.' }

  # Parameter overrides go through a temporary SAM config file, not the command line:
  # `sam` is a .cmd shim on Windows, and cmd.exe splits an argument at '&' (a DATABASE_URL
  # with ?sslmode=require&connect_timeout=10 broke that way).
  $overrides = [ordered]@{}
  $size = 0
  foreach ($parameter in $values.Keys) {
    $value = [string]$values[$parameter]
    if (-not $value) { continue }  # left to the template's default
    if ($value -match '["''\\]') { Fail "The value for $parameter contains a quote or backslash, which SAM parameter overrides can't carry." }
    $size += $value.Length
    $overrides[$parameter] = $value
  }
  if ($size -gt 3600) { Write-Warning "The settings total $size characters; Lambda environment variables are limited to 4096 bytes." }
  if ($StaticIp) { $overrides['StaticEgress'] = 'true' }
  if ($DomainName) { $overrides['DomainName'] = $DomainName }
  if ($certificateArn) { $overrides['CertificateArn'] = $certificateArn }
  if ($hostedZoneId) { $overrides['HostedZoneId'] = $hostedZoneId }

  # Quotes and backslashes are refused above, so a value needs no TOML escaping; only
  # values with spaces are wrapped (SAM splits the string like a shell would).
  $pairs = foreach ($parameter in $overrides.Keys) {
    $value = $overrides[$parameter]
    if ($value -match '\s') { "$parameter=\`"$value\`"" } else { "$parameter=$value" }
  }
  $toml = "version = 0.1`n[default.deploy.parameters]`nparameter_overrides = `"" + ($pairs -join ' ') + "`"`n"
  $configFile = Join-Path ([IO.Path]::GetTempPath()) ("market-moves-" + [Guid]::NewGuid().ToString('N') + '.toml')

  Push-Location $root
  try {
    Step 'sam build (builds the Lambda container image with Docker)'
    Run 'sam' @('build', '--template-file', 'template.yaml')

    Step 'sam deploy'
    [IO.File]::WriteAllText($configFile, $toml)  # holds secrets; deleted right after
    Run 'sam' @('deploy', '--config-file', $configFile, '--config-env', 'default',
        '--stack-name', $StackName, '--region', $Region,
        '--capabilities', 'CAPABILITY_IAM', '--resolve-s3', '--resolve-image-repos',
        '--no-confirm-changeset', '--no-fail-on-empty-changeset')
  }
  finally {
    Remove-Item -LiteralPath $configFile -Force -ErrorAction SilentlyContinue
    Pop-Location
  }

  if ($RunMigrations) {
    Step 'Applying database migrations (python -m database.migrate)'
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }
    $env:DATABASE_URL = $databaseUrl
    Push-Location (Join-Path $root 'backend\src')
    try { Run $python @('-m', 'database.migrate') }
    finally { Pop-Location; Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue }
    Write-Host 'On a shared database, re-run database/roles.sql after a new migration (backend/src/database/docs/retention-and-access.md).'
  }
}

# --- frontend -------------------------------------------------------------------

Step 'Reading stack outputs'
$json = Capture 'aws' (@('cloudformation', 'describe-stacks', '--stack-name', $StackName, '--query', 'Stacks[0].Outputs', '--output', 'json') + $regionArgs)
if (-not $json) { Fail "Stack '$StackName' has no outputs. Deploy the backend first (omit -SkipBackend)." }
$out = @{}
foreach ($o in ($json | ConvertFrom-Json)) { $out[$o.OutputKey] = $o.OutputValue }

if (-not $SkipFrontend) {
  $frontend = Join-Path $root 'frontend'
  Push-Location $frontend
  try {
    Step 'Building the frontend (npm ci, npm run build)'
    Run 'npm' @('ci')
    Run 'npm' @('run', 'build')
  }
  finally { Pop-Location }

  $dist = Join-Path $frontend 'dist'
  $bucket = "s3://$($out['SiteBucketName'])"
  Step "Uploading to $bucket"
  Run 'aws' (@('s3', 'sync', $dist, $bucket, '--delete', '--exclude', 'index.html',
      '--cache-control', 'public,max-age=31536000,immutable') + $regionArgs)
  Run 'aws' (@('s3', 'cp', (Join-Path $dist 'index.html'), "$bucket/index.html",
      '--cache-control', 'no-cache', '--content-type', 'text/html') + $regionArgs)

  Step 'Invalidating CloudFront'
  Run 'aws' @('cloudfront', 'create-invalidation', '--distribution-id', $out['DistributionId'], '--paths', '/*')
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "API (Function URL):  $($out['FunctionUrl'])   <- use this in frontend/vercel.json"
Write-Host "Health check:        $($out['FunctionUrl'])health"
if ($out['StaticEgressIp']) {
  Write-Host "Outbound IP:         $($out['StaticEgressIp'])/32   <- add this to the database allow list" -ForegroundColor Yellow
}
Write-Host "Site:                $($out['SiteUrl'])/Dashboard"
Write-Host "OAuth redirect URI:  $($out['OAuthRedirectUri'])  (add it to the Google OAuth client's authorised redirect URIs)"
if ($DomainName -and -not $hostedZoneId) {
  Write-Host "`nDNS: point $DomainName at $($out['CloudFrontDomain']) (an ALIAS/ANAME or CNAME-flattening record for an apex name)," -ForegroundColor Yellow
  Write-Host 'or move the domain to a Route 53 hosted zone and rerun this script.' -ForegroundColor Yellow
}
