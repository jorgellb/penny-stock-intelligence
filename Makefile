.PHONY: help install dev test lint typecheck format migrate docker-up docker-up-prod docker-down docker-logs clean audit ci-local

help:
	@echo "Penny Stock Intelligence Engine - Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  make install      - Install dependencies"
	@echo "  make dev          - Run development server"
	@echo "  make worker       - Run background worker"
	@echo "  make dashboard    - Run Streamlit dashboard"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run ruff linter"
	@echo "  make typecheck    - Run mypy type checker"
	@echo "  make format       - Format code with ruff"
	@echo ""
	@echo "Database:"
	@echo "  make migrate      - Run database migrations"
	@echo "  make migrate-create - Create new migration"
	@echo "  make db-reset     - Reset database (WARNING: destroys data)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up    - Start services (dev overlay with local defaults)"
	@echo "  make docker-up-prod - Start with production compose (requires .env secrets)"
	@echo "  make docker-down  - Stop all services"
	@echo "  make docker-logs  - View docker logs"
	@echo "  make docker-build - Build docker images"
	@echo "  make audit        - Run pip-audit on dependencies"
	@echo "  make ci-local     - Lint + typecheck + unit tests (CI parity)"
	@echo ""
	@echo "Application:"
	@echo "  make scan         - Run scanner once"
	@echo "  make scan-premarket - Run premarket scan"
	@echo "  make scan-intraday  - Run intraday scan"
	@echo "  make analyze SYMBOL=ABCD - Analyze specific symbol"
	@echo "  make health       - Check service health"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        - Clean build artifacts"

install:
	pip install --upgrade pip
	pip install -e ".[dev,dashboard]"

dev:
	ENVIRONMENT=development DEBUG=true uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	ENVIRONMENT=development DEBUG=true python -m app.jobs.scheduler

dashboard:
	streamlit run dashboard/main.py --server.port 8501

test:
	pytest -v --tb=short

test-unit:
	pytest tests/unit -v --tb=short

test-integration:
	pytest tests/integration -v --tb=short

test-cov:
	pytest --cov=app --cov-report=term-missing --cov-report=html

lint:
	ruff check app/ tests/

lint-fix:
	ruff check --fix app/ tests/

typecheck:
	mypy app/

format:
	ruff format app/ tests/

migrate:
	alembic upgrade head

migrate-create:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

db-reset:
	@read -p "This will destroy all data. Continue? (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		alembic downgrade base; \
		alembic upgrade head; \
	fi

docker-up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

docker-up-prod:
	@test -n "$${POSTGRES_USER}" -a -n "$${POSTGRES_PASSWORD}" -a -n "$${DATABASE_URL}" -a -n "$${API_KEY}" || \
		(echo "Missing required env: POSTGRES_USER, POSTGRES_PASSWORD, DATABASE_URL, API_KEY (see .env.example)"; exit 1)
	docker compose up --build -d

docker-down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

docker-down-volumes:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v

docker-logs:
	docker compose logs -f

docker-build:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build

docker-restart:
	docker compose restart

audit:
	pip install pip-audit >/dev/null 2>&1 || true
	pip-audit

ci-local:
	ruff check app/ tests/
	ruff format --check app/ tests/
	mypy app/
	pytest tests/unit -q --tb=short

scan:
	python -m app.cli scan

scan-premarket:
	python -m app.cli scan --mode premarket

scan-intraday:
	python -m app.cli scan --mode intraday

analyze:
	@if [ -z "$(SYMBOL)" ]; then echo "Usage: make analyze SYMBOL=ABCD"; exit 1; fi
	python -m app.cli analyze $(SYMBOL)

health:
	curl -s http://localhost:8000/health | jq .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov dist build *.egg-info 2>/dev/null || true

pre-commit:
	pre-commit run --all-files

pre-commit-install:
	pre-commit install

generate-openapi:
	curl -s http://localhost:8000/openapi.json > docs/openapi.json