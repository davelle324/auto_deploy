.PHONY: install run test lint security check clean docker-build docker-up docker-down fly-deploy fly-logs fly-secrets fly-status

install:
	pip install -r requirements.txt

run:
	uvicorn main:app --reload

test:
	python -m pytest tests/ -v

lint:
	pylint main.py config.py database.py models.py schemas.py security.py routers/ integrations/

security:
	bandit -r main.py config.py database.py models.py schemas.py security.py routers/ integrations/

check: lint security test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -f auto_deploy.db

# Fly.io targets — requires `fly` CLI installed and `fly auth login` completed
fly-deploy:
	fly deploy

fly-logs:
	fly logs

fly-secrets:
	@echo "Usage: make fly-secrets KEY=value KEY2=value2"
	@echo "Example: make fly-secrets APP_PASSWORD=hunter2 SECRET_KEY=abc123"
	fly secrets set $(filter-out $@,$(MAKECMDGOALS))

fly-status:
	fly status

# Docker targets — requires Docker and Docker Compose installed
docker-build:
	docker build -t auto-deploy .

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
