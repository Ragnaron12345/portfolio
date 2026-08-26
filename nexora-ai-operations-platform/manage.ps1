[CmdletBinding()]
param(
    [ValidateSet("Help", "Setup", "Config", "Up", "UpCache", "Seed", "SeedEval", "Down", "Logs", "Lint", "Test", "Frontend", "CI")]
    [string]$Task = "Help"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-InDirectory {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Push-Location -LiteralPath $Path
    try {
        Invoke-Checked $Command
    }
    finally {
        Pop-Location
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Task) {
        "Help" {
            @"
Nexora task runner

  .\manage.ps1 Setup      Create .env from .env.example if absent
  .\manage.ps1 Config     Validate Docker Compose configuration
  .\manage.ps1 Up         Build and start required services
  .\manage.ps1 UpCache    Start required services plus optional Redis
  .\manage.ps1 Seed       Load synthetic documents and demo requests
  .\manage.ps1 SeedEval   Seed demo data and run the measured 40-case suite
  .\manage.ps1 Down       Stop services (preserves database volume)
  .\manage.ps1 Logs       Follow service logs
  .\manage.ps1 Lint       Run backend Ruff checks locally
  .\manage.ps1 Test       Run backend pytest locally
  .\manage.ps1 Frontend   Run frontend typecheck, tests, and build locally
  .\manage.ps1 CI         Run lint, tests, frontend checks, and Compose validation
"@
        }
        "Setup" {
            if (Test-Path -LiteralPath ".env") {
                Write-Host ".env already exists; it was not changed."
            }
            else {
                Copy-Item -LiteralPath ".env.example" -Destination ".env"
                Write-Host "Created .env. Replace every placeholder before starting services."
            }
            Write-Host ".env.local is reserved for provider secrets and is never changed by this script."
        }
        "Config" {
            Invoke-Checked { docker compose config --quiet }
        }
        "Up" {
            Invoke-Checked { docker compose up --build -d }
        }
        "UpCache" {
            Invoke-Checked { docker compose --profile cache up --build -d }
        }
        "Seed" {
            Invoke-Checked { docker compose exec backend python -m app.seed_demo }
        }
        "SeedEval" {
            Invoke-Checked { docker compose exec backend python -m app.seed_demo --eval }
        }
        "Down" {
            Invoke-Checked { docker compose down --remove-orphans }
        }
        "Logs" {
            Invoke-Checked { docker compose logs --follow --tail=200 }
        }
        "Lint" {
            Invoke-InDirectory "backend" { python -m ruff check app tests alembic }
        }
        "Test" {
            Invoke-InDirectory "backend" { python -m pytest }
        }
        "Frontend" {
            Invoke-InDirectory "frontend" {
                pnpm run typecheck
                if ($LASTEXITCODE -eq 0) { pnpm run test }
                if ($LASTEXITCODE -eq 0) { pnpm run build }
            }
        }
        "CI" {
            Invoke-InDirectory "backend" { python -m ruff check app tests alembic }
            Invoke-InDirectory "backend" { python -m pytest }
            Invoke-InDirectory "frontend" {
                pnpm run typecheck
                if ($LASTEXITCODE -eq 0) { pnpm run test }
                if ($LASTEXITCODE -eq 0) { pnpm run build }
            }
            Invoke-Checked { docker compose config --quiet }
        }
    }
}
finally {
    Pop-Location
}
