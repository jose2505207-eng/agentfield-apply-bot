.PHONY: dev build start docker-build docker-run

# Local development: run FastAPI with hot-reload (frontend must be built first or run separately)
dev:
	uvicorn src.api.main:app --reload --port 8000

# Build Next.js static export
build-frontend:
	cd frontend && npm install && npm run build

# Full local setup: build frontend then start the single-process server
build: build-frontend
	@echo "Build complete. Run 'make start' to serve."

start:
	uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Docker
docker-build:
	docker build -t agentfield-apply-bot .

docker-run:
	docker run --rm -p 8000:8000 \
		--env-file .env \
		-v $(PWD)/data:/app/data \
		agentfield-apply-bot
