# Offline check in the envelope the draft case names: Python 3.11, no GPU.
# Build needs the network once (pytest); the run does not:
#   docker build -t genesis-audit-env .
#   docker run --rm --network none genesis-audit-env
FROM python:3.11-slim

# /app on the path: `import judge_adapter` works from /app and from a jury script anywhere in the container.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app:/app/src PYTHONHASHSEED=0
RUN pip install --no-cache-dir pytest==9.2.0 pytest-cov==7.1.0

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE judge_adapter.py trajectories.jsonl ./
COPY demo ./demo
COPY src ./src
COPY policies ./policies
COPY baselines ./baselines
COPY tools ./tools
COPY tests ./tests
COPY docs ./docs
COPY episodes ./episodes

# The evaluator runs as root. Policies run as an unprivileged user (setuid backend), and that user
# may read the interpreter and /app/policies, nothing else: not truth, not the public records
# (those cost steps), not the source, tests or documents. An actual permission boundary.
# `umask 077` keeps anything the evaluator writes later root-only as well.
RUN chmod -R go-rwx /app && chmod 755 /app && chmod -R a+rX /app/policies

# Tests, then the jury adapter (import from outside /app, its conformance tests, the baselines through it), then
# the self-check, then the scale measurements (their summary is printed; their exit status counts).
CMD ["sh", "-c", "umask 077 && python -m pytest -p no:cacheprovider && (cd / && python -c 'import judge_adapter; print(judge_adapter.ADAPTER_VERSION, judge_adapter.ENV_VERSION)') && python -m pytest -p no:cacheprovider tests/test_judge_adapter.py tests/test_judge_schemas.py && python tools/judge_run.py --summary /tmp/judge/summary.json --trajectories /tmp/judge/trajectories.jsonl --export-root /tmp/judge/episodes && python -m genesis_audit check && python -m genesis_audit measure > /tmp/scale.json; status=$?; head -24 /tmp/scale.json 2>/dev/null; exit $status"]
