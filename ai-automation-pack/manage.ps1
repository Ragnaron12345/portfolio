[CmdletBinding()]
param(
    [ValidateSet(
        "Help", "Setup", "Config", "Up", "Health", "ImportWorkflows",
        "Seed", "Demo", "Down", "Logs", "Lint", "Test", "Frontend", "CI"
    )]
    [string]$Task = "Help"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([Parameter(Mandatory)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-InDirectory {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][scriptblock]$Command
    )
    Push-Location -LiteralPath $Path
    try { Invoke-Checked $Command }
    finally { Pop-Location }
}

function Wait-Http {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [int]$TimeoutSeconds = 180
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "$Name is ready: $Uri"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name did not become ready within $TimeoutSeconds seconds: $Uri"
}

Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Task) {
        "Help" {
            @"
AI Automation Pack task runner

  .\manage.ps1 Setup             Create .env from the safe template
  .\manage.ps1 Config            Validate the resolved Compose model
  .\manage.ps1 Up                Build, import workflows, start, and await health
  .\manage.ps1 Health            Check API, n8n, and UI health
  .\manage.ps1 ImportWorkflows   Ensure versioned n8n workflows are imported
  .\manage.ps1 Seed              Seed deterministic demo records
  .\manage.ps1 Demo              Run all acceptance-oriented workflow probes
  .\manage.ps1 Down              Stop services; preserve PostgreSQL and n8n data
  .\manage.ps1 Logs              Follow service logs
  .\manage.ps1 Lint              Run backend lint and workflow validation
  .\manage.ps1 Test              Run backend tests and workflow validation
  .\manage.ps1 Frontend          Typecheck, test, and build the operator UI
  .\manage.ps1 CI                Run all local non-container verification
"@
        }
        "Setup" {
            if (Test-Path -LiteralPath ".env") {
                Write-Host ".env already exists; it was not changed."
            }
            else {
                Copy-Item -LiteralPath ".env.example" -Destination ".env"
                Write-Host "Created .env. Replace placeholder passwords and tokens."
            }
            Write-Host "Provider credentials belong only in ignored .env.local."
        }
        "Config" {
            Invoke-Checked { docker compose config --quiet }
        }
        "Up" {
            Invoke-Checked { docker compose up --build -d }
            # The one-shot import container refreshes DB workflow versions. A
            # restart makes those versions authoritative in an already-running n8n.
            Invoke-Checked { docker compose restart n8n }
            Wait-Http "FastAPI" "http://localhost:8004/ready"
            Wait-Http "n8n" "http://localhost:5678/healthz"
            Wait-Http "Operator UI" "http://localhost:3004/healthz"
        }
        "Health" {
            Wait-Http "FastAPI" "http://localhost:8004/ready" 10
            Wait-Http "n8n" "http://localhost:5678/healthz" 10
            Wait-Http "Operator UI" "http://localhost:3004/healthz" 10
        }
        "ImportWorkflows" {
            Invoke-Checked { docker compose up -d postgres backend }
            Invoke-Checked { docker compose run --rm --no-deps n8n-import }
            Invoke-Checked { docker compose restart n8n }
            Wait-Http "n8n" "http://localhost:5678/healthz"
            Write-Host "Refreshed and published all checked-in workflow versions."
        }
        "Seed" {
            Invoke-Checked { docker compose exec -T backend python -m app.seed }
        }
        "Demo" {
            Invoke-Checked { python scripts/test_support_workflow.py }
            Invoke-Checked { python scripts/test_invoice_workflow.py }
            Invoke-Checked { python scripts/test_incident_workflow.py }
        }
        "Down" {
            Invoke-Checked { docker compose down --remove-orphans }
        }
        "Logs" {
            Invoke-Checked { docker compose logs --follow --tail=200 }
        }
        "Lint" {
            Invoke-InDirectory "automation-api" { python -m ruff check app tests }
            Invoke-Checked { python scripts/validate_workflows.py }
        }
        "Test" {
            Invoke-InDirectory "automation-api" { python -m pytest }
            Invoke-Checked { python scripts/validate_workflows.py }
        }
        "Frontend" {
            Invoke-InDirectory "frontend" {
                pnpm run typecheck
                if ($LASTEXITCODE -eq 0) { pnpm run test }
                if ($LASTEXITCODE -eq 0) { pnpm run build }
            }
        }
        "CI" {
            Invoke-InDirectory "automation-api" { python -m ruff check app tests }
            Invoke-InDirectory "automation-api" { python -m pytest }
            Invoke-InDirectory "frontend" {
                pnpm run typecheck
                if ($LASTEXITCODE -eq 0) { pnpm run test }
                if ($LASTEXITCODE -eq 0) { pnpm run build }
            }
            Invoke-Checked { python scripts/validate_workflows.py }
            Invoke-Checked { docker compose config --quiet }
        }
    }
}
finally {
    Pop-Location
}
