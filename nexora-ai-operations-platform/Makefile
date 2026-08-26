.DEFAULT_GOAL := help

.PHONY: help setup config up up-cache seed seed-eval down logs lint test frontend-check ci

help: ## Show available tasks
	@awk 'BEGIN {FS = ":.*## "; printf "Nexora tasks:\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create .env from the safe template when it does not exist
	@test -f .env || cp .env.example .env
	@echo "Review .env and replace all placeholder values before starting services."

config: ## Validate the resolved Docker Compose configuration
	docker compose config --quiet

up: ## Build and start the required services
	docker compose up --build -d

up-cache: ## Build and start required services plus optional Redis
	docker compose --profile cache up --build -d

seed: ## Load synthetic documents and demo requests into the running backend
	docker compose exec backend python -m app.seed_demo

seed-eval: ## Seed demo data and run the measured 40-case comparison
	docker compose exec backend python -m app.seed_demo --eval

down: ## Stop services without deleting the database volume
	docker compose down --remove-orphans

logs: ## Follow service logs
	docker compose logs --follow --tail=200

lint: ## Run backend linting locally
	cd backend && python -m ruff check app tests alembic

test: ## Run backend tests locally
	cd backend && python -m pytest

frontend-check: ## Typecheck, test, and build the frontend locally
	cd frontend && pnpm run typecheck && pnpm run test && pnpm run build

ci: lint test frontend-check config ## Run the same core checks as CI
