$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
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

Push-Location (Join-Path $RepositoryRoot "backend")
try {
    Invoke-Checked "uv" @("run", "ruff", "format", "--check", ".")
    Invoke-Checked "uv" @("run", "ruff", "check", ".")
    Invoke-Checked "uv" @("run", "pyright")
    Invoke-Checked "uv" @("run", "pytest")
}
finally {
    Pop-Location
}

Push-Location (Join-Path $RepositoryRoot "frontend")
try {
    Invoke-Checked $npmCommand @("run", "test")
    Invoke-Checked $npmCommand @("run", "typecheck")
    Invoke-Checked $npmCommand @("run", "lint")
    Invoke-Checked $npmCommand @("run", "build")
}
finally {
    Pop-Location
}
