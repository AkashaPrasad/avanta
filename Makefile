.PHONY: help up down logs test verify fmt lint fixtures synthetic deploy

help:
	@echo "up        docker compose up (the on-premise deployment)"
	@echo "down      stop and remove containers"
	@echo "test      run the python test suite"
	@echo "verify    run the full verification loop into reports/verification/"
	@echo "lint      ruff + mypy + tsc"
	@echo "synthetic regenerate the synthetic validation set and calibration"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

test:
	./.venv/bin/python -m pytest tests -q

verify:
	./scripts/verify.sh

lint:
	./.venv/bin/python -m ruff check core api scripts tests
	./.venv/bin/python -m mypy --ignore-missing-imports core
	cd web && npx tsc --noEmit

synthetic:
	./.venv/bin/python scripts/make_synthetic_set.py --ais fixtures/ais/north_sea_live.json --offshore-km 25
