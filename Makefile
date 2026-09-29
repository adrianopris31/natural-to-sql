.PHONY: dev dev-backend dev-frontend test lint eval infra-up infra-down docker-build docker-up docker-down clean

infra-up:
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

dev:
	@echo "Starting Natural-to-SQL infra..."
	make infra-up
	@echo "Starting backend and frontend concurrently (Ctrl+C to stop)..."
	(trap 'kill 0' SIGINT; (cd backend && uv run uvicorn app.main:app --reload --port 8000) & (cd frontend && pnpm dev) & wait)

test:
	@echo "Running backend tests..."
	cd backend && uv run pytest
	@echo "Running frontend tests..."
	cd frontend && pnpm test

lint:
	@echo "Running backend quality checks..."
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy app
	@echo "Running frontend quality checks..."
	cd frontend && pnpm lint

eval:
	cd backend && uv run python -m evals.run --model qwen2.5-coder:7b

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache frontend/.next
