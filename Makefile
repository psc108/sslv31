.PHONY: dev dev-backend dev-frontend install install-backend install-frontend lint typecheck test clean

# Development
dev: dev-backend dev-frontend

dev-backend:
	cd backend && ../backend/venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# Installation
install: install-backend install-frontend

install-backend:
	cd backend && python3 -m venv venv
	cd backend && venv/bin/pip install --upgrade pip
	cd backend && venv/bin/pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

# Quality
lint:
	cd backend && venv/bin/ruff check app/ tests/
	cd backend && venv/bin/ruff format --check app/ tests/

typecheck:
	cd backend && venv/bin/mypy app/

test:
	cd backend && venv/bin/pytest tests/ -v

# Cleanup
clean:
	rm -rf backend/venv
	rm -rf frontend/node_modules
	rm -rf frontend/dist
