# Running kinst (developer notes)

This repository contains the `kinst` utility under `kagenti/kinst` — a small CLI to orchestrate Helm charts and remote YAML templates for demos.

Quick ways to run `kinst` from the repository root:

- Wrapper script (preferred):

```bash
./scripts/kinst plan -f kagenti/kinst/docs/samples/installables.yaml -v kagenti/kinst/docs/samples/values.yaml
```

The wrapper changes into the `kagenti/kinst` subproject and runs `uv run kinst` so you can work from the repo root.

- Makefile target (convenience):

```bash
make kinst ARGS="plan -f kagenti/kinst/docs/samples/installables.yaml -v kagenti/kinst/docs/samples/values.yaml"
```

Before the first run, install dependencies for the `kinst` subproject:

```bash
cd kagenti/kinst
uv sync
```

Notes:
- `apply` performs real operations via the `helm` and `kubectl` CLIs — make sure those CLIs are installed and configured, and prefer `--dry-run` first.
- Paths passed to `kinst` may be relative to the repository root (the CLI will resolve them automatically).
- The `kinst` CLI shows a compact progress UI with a spinner and checkmarks for each step when run in a TTY.
