.PHONY: bootstrap fixtures check-fixtures openapi check-openapi types check-types live-e2e test build validate validate-fixtures guard verify

bootstrap:
	./scripts/bootstrap.sh

fixtures:
	.venv/bin/python scripts/build_network_profile.py
	.venv/bin/python scripts/build_handoff_fixtures.py

check-fixtures:
	.venv/bin/python scripts/build_handoff_fixtures.py --check

openapi:
	.venv/bin/python scripts/generate_openapi.py

check-openapi:
	.venv/bin/python scripts/generate_openapi.py --check

types: openapi
	cd frontend && npm run generate-types

generate-types: types

check-types: check-openapi
	cd frontend && npm run check-generated-types

live-e2e:
	cd frontend && npm run e2e:live

validate:
	.venv/bin/python scripts/validate_milestone0.py

validate-fixtures: validate
	.venv/bin/python -m pytest backend/tests/contract/ -v

# Static guard: prove runtime packages cannot reference expected/, ground_truth,
# or golden test-output files (blueprint §23.6, §8.2, M0-008).
guard:
	.venv/bin/python -m pytest backend/tests/contract/test_ground_truth_firewall.py -v

test: guard
	cd backend && ../.venv/bin/python -m pytest
	cd frontend && npm test

build:
	cd frontend && npm run build

# Full CI gate: validate + test + build
verify: check-fixtures check-types validate-fixtures test build
