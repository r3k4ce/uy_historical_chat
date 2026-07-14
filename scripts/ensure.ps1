param(
    [switch]$SkipHookInstall
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendPath = Join-Path $RepositoryRoot "backend"
$FrontendPath = Join-Path $RepositoryRoot "frontend"
$npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

foreach ($Command in @("uv", "node", $npmCommand)) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Missing required tool: $Command. See README.md for supported versions."
    }
}

$uvVersion = ((& uv --version) -split " ")[1]
$nodeVersion = (& node --version).TrimStart("v")
$npmVersion = (& $npmCommand --version)
if ($uvVersion -ne "0.11.26") { throw "Unsupported uv version $uvVersion; install uv 0.11.26." }
if (-not $nodeVersion.StartsWith("24.")) { throw "Unsupported Node.js version $nodeVersion; install Node.js 24." }
if (-not $npmVersion.StartsWith("11.")) { throw "Unsupported npm version $npmVersion; install npm 11." }

$PathSentinel = Join-Path $BackendPath ".venv/.artigas-project-path"
$StoredPath = if (Test-Path $PathSentinel) { (Get-Content $PathSentinel -Raw).Trim() } else { "" }
Push-Location $BackendPath
try {
    if ($StoredPath -ne $BackendPath) {
        Write-Host "Repairing backend environment for $BackendPath"
        Invoke-Checked "uv" @("sync", "--locked", "--dev", "--reinstall")
        Set-Content -Path $PathSentinel -Value $BackendPath -Encoding utf8NoBOM
    }
    else {
        & uv sync --locked --dev --check
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Synchronizing backend dependencies"
            Invoke-Checked "uv" @("sync", "--locked", "--dev")
        }
    }
}
finally { Pop-Location }

$LockFile = Join-Path $FrontendPath "package-lock.json"
$LockSentinel = Join-Path $FrontendPath "node_modules/.artigas-package-lock.sha256"
$LockHash = (Get-FileHash -Algorithm SHA256 $LockFile).Hash.ToLowerInvariant()
$StoredHash = if (Test-Path $LockSentinel) { (Get-Content $LockSentinel -Raw).Trim() } else { "" }
Push-Location $FrontendPath
try {
    & $npmCommand ls --depth=0 *> $null
    $DependenciesValid = $LASTEXITCODE -eq 0
    if ($StoredHash -ne $LockHash -or -not $DependenciesValid) {
        Write-Host "Installing frontend dependencies from package-lock.json"
        Invoke-Checked $npmCommand @("ci")
        Set-Content -Path $LockSentinel -Value $LockHash -Encoding utf8NoBOM
    }
}
finally { Pop-Location }

if (-not $SkipHookInstall -and -not $env:ARTIGAS_SKIP_HOOK_INSTALL -and -not $env:CI) {
    $Python = Join-Path $BackendPath ".venv/Scripts/python.exe"
    if (-not (Test-Path $Python)) { $Python = Join-Path $BackendPath ".venv/bin/python" }
    Invoke-Checked $Python @("-m", "pre_commit", "install", "--hook-type", "pre-commit", "--overwrite")
}
