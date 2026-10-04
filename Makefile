.PHONY: install-dev lint format test check build-image

install-dev:
	python -m pip install -e '.[dev]'

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

test:
	pytest

check:
	ruff format --check src tests
	ruff check src tests
	pytest

build-image:
	docker build -t gitlab-harbor-sync:dev .
