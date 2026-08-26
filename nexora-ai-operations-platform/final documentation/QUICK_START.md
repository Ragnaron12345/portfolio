# Quick Start

## Required applications

- Docker Desktop with Docker Compose v2.24 or newer
- PowerShell 7
- At least 4 GB of free memory

Python, Node.js, and pnpm are required only for development outside Docker.

## Start Nexora

Open PowerShell in the project directory:

```powershell
cd "<path-to-nexora-ai-operations-platform>"
.\manage.ps1 Setup
.\manage.ps1 Up
.\manage.ps1 Seed
```

`Setup` creates the local `.env` file without overwriting an existing one. Before the first start, replace `POSTGRES_PASSWORD` in `.env` with a long URL-safe password.

## Configure an AI provider

Provider keys belong only in ignored local files in the project root. Do not add real keys to `.env.example`, source code, frontend variables, documentation, or Git.

OpenAI uses `.env.local`:

```dotenv
OPENAI_API_KEY=replace-with-your-runtime-key
NEXORA_AI_PROVIDER_MODE=openai
```

AI Prime Tech uses `.env.aiprimetech.local`:

```dotenv
AIPRIMETECH_API_KEY=replace-with-your-runtime-key
NEXORA_AI_PROVIDER_MODE=aiprimetech
```

Set `NEXORA_AI_PROVIDER_MODE=auto` to enable configured remote providers with the bounded local fallback, or `mock` for deterministic offline operation. Model IDs can be changed in `.env` using `NEXORA_OPENAI_CHAT_MODEL`, `NEXORA_OPENAI_EMBEDDING_MODEL`, and the `NEXORA_AIPRIMETECH_*_MODEL` variables.

After changing a key, mode, or model ID, apply the new environment:

```powershell
.\manage.ps1 Up
Invoke-RestMethod http://localhost:3000/api/v1/health
```

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
