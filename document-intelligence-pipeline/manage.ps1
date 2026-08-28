[CmdletBinding()]
param(
    [ValidateSet("Help", "Setup", "Up", "Down", "Logs", "Seed", "Test", "Frontend", "CI", "Config")]
    [string]$Task = "Help"
)

$ErrorActionPreference = "Stop"
$Python = if (Test-Path -LiteralPath ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Invoke-Checked {
    param([Parameter(Mandatory)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE." }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Task) {
        "Help" { @"
DocIntel task runner
  .\manage.ps1 Setup      Create .env and install local dependencies
  .\manage.ps1 Up         Build and start PostgreSQL, API, and UI
  .\manage.ps1 Down       Stop containers and preserve data
  .\manage.ps1 Seed       Generate 64 synthetic documents and seed the demo
  .\manage.ps1 Test       Run backend tests
  .\manage.ps1 Frontend   Run typecheck, tests, and production build
  .\manage.ps1 CI         Run all local verification and Compose validation
"@ }
        "Setup" {
            if (-not (Test-Path -LiteralPath ".env")) { Copy-Item -LiteralPath ".env.example" -Destination ".env" }
            if (-not (Test-Path -LiteralPath ".venv")) { python -m venv .venv }
            Invoke-Checked { & ".venv\Scripts\python.exe" -m pip install -e ".\backend[dev]" }
            Push-Location frontend
            try { Invoke-Checked { pnpm install } } finally { Pop-Location }
        }
        "Up" { Invoke-Checked { docker compose up --build -d } }
        "Down" { Invoke-Checked { docker compose down --remove-orphans } }
        "Logs" { Invoke-Checked { docker compose logs --follow --tail=200 } }
        "Seed" {
            Invoke-Checked { & $Python ".\scripts\generate_dataset.py" }
            Invoke-Checked { docker compose exec backend python -m app.seed_demo --reset }
        }
        "Test" { Push-Location backend; try { Invoke-Checked { & "..\$Python" -m pytest } } finally { Pop-Location } }
        "Frontend" { Push-Location frontend; try { Invoke-Checked { pnpm run typecheck }; Invoke-Checked { pnpm run test }; Invoke-Checked { pnpm run build } } finally { Pop-Location } }
        "Config" { Invoke-Checked { docker compose config --quiet } }
        "CI" {
            Push-Location backend; try { Invoke-Checked { & "..\$Python" -m ruff check app tests }; Invoke-Checked { & "..\$Python" -m pytest } } finally { Pop-Location }
            Push-Location frontend; try { Invoke-Checked { pnpm run typecheck }; Invoke-Checked { pnpm run test }; Invoke-Checked { pnpm run build } } finally { Pop-Location }
            Invoke-Checked { docker compose config --quiet }
        }
    }
}
finally { Pop-Location }
