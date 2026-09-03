[CmdletBinding()]
param(
    [ValidateSet("Help", "Setup", "Config", "Up", "Down", "Logs", "Test", "Frontend", "CI")]
    [string]$Task = "Help"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([Parameter(Mandatory)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE." }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Task) {
        "Help" {
            @"
EvalForge task runner

  .\manage.ps1 Setup      Create ignored .env from .env.example when absent
  .\manage.ps1 Config     Validate Docker Compose configuration
  .\manage.ps1 Up         Build and start PostgreSQL, API and UI
  .\manage.ps1 Down       Stop services and preserve the database volume
  .\manage.ps1 Logs       Follow service logs
  .\manage.ps1 Test       Run backend tests in a clean container
  .\manage.ps1 Frontend   Run frontend tests, typecheck and build in a container
  .\manage.ps1 CI         Run tests, frontend checks and Compose validation
"@
        }
        "Setup" {
            if (Test-Path -LiteralPath ".env") { Write-Host ".env already exists; it was not changed." }
            else { Copy-Item -LiteralPath ".env.example" -Destination ".env"; Write-Host "Created .env. Replace the database password before any shared deployment." }
        }
        "Config" { Invoke-Checked { docker compose config --quiet } }
        "Up" {
            $evalforgeCommit = git rev-parse --short HEAD 2>$null
            if ($LASTEXITCODE -ne 0) { $evalforgeCommit = "unavailable" }
            $env:EVALFORGE_GIT_COMMIT = $evalforgeCommit
            Invoke-Checked { docker compose up --build -d }
        }
        "Down" { Invoke-Checked { docker compose down --remove-orphans } }
        "Logs" { Invoke-Checked { docker compose logs --follow --tail=200 } }
        "Test" { Invoke-Checked { docker compose run --rm --no-deps backend python -m pytest } }
        "Frontend" {
            Invoke-Checked { docker build --target build -t evalforge-frontend-check ./frontend }
            Invoke-Checked { docker run --rm evalforge-frontend-check sh -c "pnpm run test && pnpm run typecheck && pnpm run build" }
        }
        "CI" {
            Invoke-Checked { docker compose build }
            Invoke-Checked { docker compose run --rm --no-deps backend python -m ruff check app tests }
            Invoke-Checked { docker compose run --rm --no-deps backend python -m pytest }
            Invoke-Checked { docker build --target build -t evalforge-frontend-check ./frontend }
            Invoke-Checked { docker run --rm evalforge-frontend-check sh -c "pnpm run test && pnpm run typecheck && pnpm run build" }
            Invoke-Checked { docker compose config --quiet }
        }
    }
}
finally { Pop-Location }
