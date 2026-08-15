.PHONY: install run test lint security check clean

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
