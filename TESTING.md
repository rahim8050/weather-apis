# Testing

This repo uses pytest + pytest-django.

## Run the test suite

```bash
.venv/bin/pytest
```

## Run tests with coverage

```bash
.venv/bin/pytest --cov=. --cov-report=term-missing --cov-report=xml
```

## Enforce the coverage gate locally

```bash
COVERAGE_FAIL_UNDER=98 .venv/bin/pytest --cov=. --cov-report=term-missing \
  --cov-report=xml --cov-fail-under="${COVERAGE_FAIL_UNDER}"
```
