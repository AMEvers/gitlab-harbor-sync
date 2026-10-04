# Contributing

## Local development

Python 3.12 is the supported development version.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make check
```

## Pull requests

Keep changes focused and include or update tests for behavior changes. CI verifies
Ruff formatting/linting, unit tests, and that the container image builds.

Do not commit real GitLab or Harbor credentials. Use placeholder values in
examples and Kubernetes manifests.
