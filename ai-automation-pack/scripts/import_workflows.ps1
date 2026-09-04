[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    docker compose up -d postgres backend
    if ($LASTEXITCODE -ne 0) { throw "Could not start PostgreSQL and backend." }

    docker compose run --rm --no-deps n8n-import
    if ($LASTEXITCODE -ne 0) { throw "n8n workflow import or publication failed." }

    docker compose restart n8n
    if ($LASTEXITCODE -ne 0) { throw "Could not restart n8n after import." }

    Write-Host "Refreshed the three workflows and shared error handler from checked-in JSON, then published them."
}
finally {
    Pop-Location
}
