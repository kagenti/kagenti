# kinst (prototype)

Minimal Python prototype for `kinst` — a CLI to orchestrate Helm charts and remote YAMLs.

This prototype is non-destructive and focuses on validation, plan generation and file format.

Prerequisites
- Python 3.9+
- `uv` (you requested `uv` for dependency management). Install it first with your chosen method, for example:

```bash
python -m pip install uv
```

Install dependencies (using `uv`)

```bash
# from repo root (where pyproject.toml is located)
uv install
```

Run the prototype

```bash
# run the plan command
kinst plan -f kagenti/kinst/samples/installables.yaml -v kagenti/kinst/samples/values.yaml

# or directly via module
python -m kagenti.kinst.cli plan -f kagenti/kinst/samples/installables.yaml -v kagenti/kinst/samples/values.yaml
```

Notes
- This is a small scaffold: the `plan` command validates `installables.yaml` against the JSON Schema in `kinst/schema` and resolves conditions/namespaces from `values.yaml` and prints a plan. It does not execute `helm` or `kubectl`.
- The `pyproject.toml` lists runtime dependencies (`typer`, `PyYAML`, `jsonschema`, `requests`, `rich`). Using `uv` will install them into a virtual environment.

Next steps you can ask me to implement:
- wire actual helm/kubectl operations
- add tests and CI
- add `uv` lockfile or pinned environment

kubectl-label installables
-------------------------

`kubectl-label` is a small installable type that applies one or more labels to a Kubernetes namespace.

Example (inline labels, default overwrite behavior):

```yaml
- id: label-team1
	type: kubectl-label
	namespace: team1.namespace      # dotted path into values.yaml or literal namespace
	labels:
		team: team1
		env: dev
	condition: team1.enabled
```

Notes:
- `override` (boolean, optional): when true (default) the CLI passes `--overwrite` to `kubectl label` so labels will be replaced; set `override: false` to avoid changing existing labels.
- `labelsPath` (string, optional): instead of inline `labels`, you can reference a dotted path in `values.yaml` that resolves to a mapping of labels.
- Label values are normalized to strings; booleans become the lowercase strings `"true"`/`"false"` to match common YAML boolean literals.

Environment variable substitution in `values.yaml`
-------------------------------------------------

You can reference environment variables inside `values.yaml` using the `${VAR}` syntax. These are resolved from the process environment by default.

Examples in `values.yaml`:

```yaml
db:
	password: ${DB_PASSWORD}
registry:
	user: ${GHCR_USER}
	token: ${GHCR_TOKEN:-default-token}
```

Features:
- `${VAR}` pulls from environment; if not found you can provide a `.env` file with `-e/--env-file`.
- Shell-style default `${VAR:-default}` is supported — when `VAR` is unset the `default` text will be used.
- Use `--allow-missing-env` to substitute missing variables with an empty string rather than failing.

Example using a `.env` file (do NOT commit this file):

```
DB_PASSWORD=mysecret
GHCR_USER=myuser
GHCR_TOKEN=mytoken
```

Then run:

```bash
./scripts/kinst apply -f deployments/kinst/environments/dev/installables.yaml -v deployments/kinst/environments/dev/values.yaml -e deployments/kinst/environments/dev/.env
```

Example (no-overwrite):

```yaml
- id: label-team1-no-overwrite
	type: kubectl-label
	namespace: team1.namespace
	labels:
		team: team1
	override: false
	condition: team1.enabled
```
