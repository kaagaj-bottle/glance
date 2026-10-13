# Repository instructions

## Project

- Glance is a Python 3.13 package managed with `uv`.
- Glance is planned as a Linux desktop app for screenshots, region capture, and screen recording. Its distinguishing workflows are OCR, translation, and visual search on a selected area or the whole screen.
- Flatpak is the intended distribution format. Windows support is a possible later direction and is outside the current scope.
- Application code lives under `src/glance/`. The CLI entry point is `glance.app:main`, declared in `pyproject.toml`.
- `src/glance/capture/` and `src/glance/ui/` are package areas. Their APIs and implementation have not been defined yet; check the task requirements before extending them.

## Working in this repo

- Use `uv` for dependency and environment commands, and keep `pyproject.toml` and `uv.lock` in sync when dependencies change.
- Keep changes focused. Do not add dependencies, frameworks, or architectural layers without a concrete need.
- Add focused tests for new behavior under `src/tests/`. Use the test tooling already present in the repo; if none exists, choose the smallest suitable approach for the change.
- Run the checks relevant to the files you change. For CLI changes, `uv run glance` is a useful smoke test.
- Commit in small, meaningful steps (for example logic, then UI, then docs), each with its own tests. Doing a whole piece of work in a single commit is acceptable but not desirable.
- Update `README.md` when you add setup steps, user-facing commands, or behavior that needs documentation.
