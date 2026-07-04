# Release Checklist

1. Run backend tests: `uv run pytest -q`.
2. Run frontend lint/unit/build: `cd web && npm run lint && npm test && npm run build`.
3. Run Playwright: `cd web && npm run test:e2e`.
4. Run wheel smoke: `uv run python -m build` and install the wheel in a clean venv.
5. Run manual LLM eval when an API key is available.
6. Seed examples in a clean `QUANTBENCH_HOME` and start `quantbench serve`.
7. Review `LAUNCH_READINESS.md` and update resolved launch gaps.
8. Bump `pyproject.toml` version and `CHANGELOG.md`.
9. Create a signed git tag.
10. Publish release notes with platform, API safety, data limitations, and risk disclaimer.
