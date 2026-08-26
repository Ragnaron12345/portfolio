# Quick Start

## Required applications

- Docker Desktop with Docker Compose v2.24 or newer
- PowerShell 7
- At least 4 GB of free memory

Python, Node.js, and pnpm are required only for development outside Docker.

## Start Nexora

Open PowerShell in the project directory:

```powershell
cd "C:\Codex\19\1_Nexora AI Operations Platform"
.\manage.ps1 Setup
.\manage.ps1 Up
.\manage.ps1 Seed
```

`Setup` creates the local `.env` file without overwriting an existing one. Before the first start, replace `POSTGRES_PASSWORD` in `.env` with a long URL-safe password.

## Open the application

- Dashboard: <http://localhost:3000>
- API documentation: <http://localhost:3000/api/v1/docs>

Check service health:

```powershell
Invoke-RestMethod http://localhost:3000/api/v1/health
```

The expected status is `ok`. Remote AI credentials are optional because the project can run with its deterministic local fallback.

## Optional evaluation data

```powershell
.\manage.ps1 SeedEval
```

This loads the demo data and persists the 40-case Baseline/Improved comparison.

## Stop Nexora

```powershell
.\manage.ps1 Down
```

This stops the containers and preserves the PostgreSQL data volume.
