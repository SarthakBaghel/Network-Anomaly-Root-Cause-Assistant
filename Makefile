.PHONY: bootstrap fixtures openapi types test build validate verify

bootstrap:
	./scripts/bootstrap.sh

fixtures:
	.venv/bin/python scripts/build_scenario_bundle.py
	.venv/bin/python scripts/build_handoff_fixtures.py

openapi:
	.venv/bin/python scripts/generate_openapi.py

types: openapi
	cd frontend && npm run generate-types

test:
	cd backend && ../.venv/bin/python -m pytest
	cd frontend && npm test

build:
	cd frontend && npm run build

validate:
	.venv/bin/python scripts/validate_milestone0.py

verify: validate test build

