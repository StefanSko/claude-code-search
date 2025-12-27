# Development Workflow (TDD + Validation)

This project follows a strict test-driven workflow. Every change must be
validated with linting, type checking, unit tests.

## Required loop for each change

1. Write or update tests first (TDD).
2. Run formatting and lint checks:
   - `uv run ruff check src/ tests/`
   - `uv run ruff format src/ tests/`
3. Run type checking:
   - `uv run ty check src/`
4. Run unit tests:
   - `uv run pytest tests/unit -v`

Do not move to the next change until the full validation loop passes.