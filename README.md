# Glance

Glance is a planned Linux desktop app for capturing and understanding what is on your screen. It aims to combine familiar screenshot and screen recording tools with OCR, translation, and visual search, so you can act on content without leaving the capture workflow.

The goal is to support both a selected area and the whole screen. Planned actions include taking screenshots, recording the screen, extracting text, translating visible content, and searching for images or objects in a Google Lens-like way.

Flatpak is the intended distribution format. Windows support may be considered later, but the current focus is Linux.

## Run

Run the app from the project root:

```sh
uv run glance
```

## Tasks

Common commands are defined in `Taskfile.yml` and run with [Task](https://taskfile.dev):

```sh
task run-dev    # run the app
task run-test   # run the tests; extra unittest args go after --, e.g. task run-test -- -k portal
```

## Development checks

Install the Git hooks once:

```sh
uv run pre-commit install
```

Run all checks manually with `uv run pre-commit run --all-files`. The hooks
check whitespace and YAML, JSON, and TOML files; format and lint Python files
with Ruff; then type-check the `src` tree with Pyright. Hook versions are pinned
in `.pre-commit-config.yaml`, and the same tools are available as development
dependencies through `uv`.
