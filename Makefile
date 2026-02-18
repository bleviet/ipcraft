# ipcraft Makefile
# Provides convenient commands for testing and development

# Default target
.DEFAULT_GOAL := help

.PHONY: help test test-all test-verbose test-coverage clean install install-dev
.PHONY: test-vhdl test-verilog test-core test-generator test-parser test-roundtrip
.PHONY: lint format format-check type-check quality tox build
.PHONY: discover list-tests run-examples test-summary

help:
	@echo "ipcraft Makefile Commands:"
	@echo ""
	@echo "Testing Commands:"
	@echo "  make test              - Run all tests"
	@echo "  make test-all          - Run all tests (alias for test)"
	@echo "  make test-verbose      - Run all tests with verbose output"
	@echo "  make test-coverage     - Run tests with coverage reporting"
	@echo "  make tox               - Run tests in multiple Python versions"
	@echo ""
	@echo "Code Quality Commands:"
	@echo "  make lint              - Run code linting (flake8)"
	@echo "  make format            - Format code with black"
	@echo "  make type-check        - Run type checking with mypy"
	@echo "  make quality           - Run all quality checks"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install           - Install package in editable mode"
	@echo "  make clean             - Remove Python cache files"
	@echo "  make build             - Build distribution packages"
	@echo ""

# Main test commands
test:
	uv run pytest

test-all: test

test-verbose:
	uv run pytest -v

test-coverage:
	uv run pytest --cov=ipcraft --cov-report=term-missing

# Code quality commands
lint:
	uv run flake8 ipcraft

format:
	uv run black ipcraft

format-check:
	uv run black --check ipcraft

type-check:
	uv run mypy ipcraft

quality: lint format-check type-check
	@echo "All quality checks passed!"

# Advanced development commands
tox:
	uv run tox

build:
	uv run python -m build

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
