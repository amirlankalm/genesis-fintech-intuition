# One command reproduces every number this repository reports:  make reproduce
.PHONY: check lint test selfcheck results fixtures harness pages rubric-pdf docker-check verify measurements judge reproduce

reproduce:
	uv run python tools/write_verification.py

check: lint test selfcheck

lint:
	uv run ruff check src tests policies tools baselines judge_adapter.py
	uv run ruff format --check src tests policies tools baselines judge_adapter.py
	uv run mypy src

test:
	uv run pytest --cov=genesis_audit --cov-report=term-missing:skip-covered --cov-fail-under=80

selfcheck:
	uv run python -m genesis_audit check

results:
	uv run python -m genesis_audit baselines --write-docs

fixtures:
	uv run python -m genesis_audit build-fixtures

harness:
	uv run python -m genesis_audit harness --sheet

pages:
	for p in A B C D; do uv run python -m genesis_audit tutor $$p --render; done

rubric-pdf:
	mkdir -p out
	uv run python tools/md_to_typst.py docs/GRADING_CRITERIA.md out/GRADING_CRITERIA.typ
	typst compile out/GRADING_CRITERIA.typ docs/GRADING_CRITERIA.pdf

# The judge path: the four benchmark baselines (+ reconciliation) through judge_adapter.py on the shipped
# train and dev episodes in closed mode (summary + trajectories under out/judge/), then the adapter conformance tests.
judge:
	uv run python tools/judge_run.py --summary out/judge/summary.json --trajectories out/judge/trajectories.jsonl
	uv run pytest -p no:cacheprovider tests/test_judge_adapter.py tests/test_judge_schemas.py

# Offline container execution conforming to the 60s limit with no network at run time.
docker-check:
	docker build -t genesis-audit-env .
	docker run --rm --network none genesis-audit-env

# Run everything, on this tree, and write the log that names the tree it was run on.
verify:
	uv run python tools/write_verification.py

# Re-measure: the random baseline over 400 of its own seeds on the teaching episodes (about three minutes),
# and reading cost, time and memory on every shipped episode.
measurements:
	mkdir -p docs/measurements
	uv run python -m genesis_audit sweep --seeds 400 > docs/measurements/random_inspector_sweep.json
	uv run python -m genesis_audit measure > docs/measurements/scale.json
