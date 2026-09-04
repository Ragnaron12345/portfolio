.PHONY: help setup config up health import seed demo down logs lint test frontend ci

help:
	@echo "AI Automation Pack"
	@echo "  make setup     Copy .env.example to .env when absent"
	@echo "  make up        Build and start the complete local stack"
	@echo "  make demo      Run all three workflow probes"
	@echo "  make ci        Run local verification"

setup:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./manage.ps1 Setup

config:
	docker compose config --quiet

up:
	docker compose up --build -d

health:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./manage.ps1 Health

import:
	docker compose up -d postgres backend
	docker compose run --rm --no-deps n8n-import
	docker compose restart n8n

seed:
	docker compose exec -T backend python -m app.seed

demo:
	python scripts/test_support_workflow.py
	python scripts/test_invoice_workflow.py
	python scripts/test_incident_workflow.py

down:
	docker compose down --remove-orphans

logs:
	docker compose logs --follow --tail=200

lint:
	cd automation-api && python -m ruff check app tests
	python scripts/validate_workflows.py

test:
	cd automation-api && python -m pytest
	python scripts/validate_workflows.py

frontend:
	cd frontend && pnpm run typecheck
	cd frontend && pnpm run test
	cd frontend && pnpm run build

ci: lint test frontend config
