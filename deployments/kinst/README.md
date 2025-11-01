Kagenti kinst deployment manifests
=================================

This directory contains example kinst manifests for deploying the Kagenti project and 3rd-party charts.

Layout
------
- `environments/<env>/installables.yaml` - ordered list of installables (helm charts and kubectl templates) for the environment
- `environments/<env>/values.yaml` - values used when rendering charts and templates for the environment

How to run (from repository root)
---------------------------------
Use the repository-level helper which runs kinst in the `kagenti/kinst` subproject:

```
./scripts/kinst plan -f deployments/kinst/environments/dev/installables.yaml -v deployments/kinst/environments/dev/values.yaml

# Dry-run apply (safe):
./scripts/kinst apply -f deployments/kinst/environments/dev/installables.yaml -v deployments/kinst/environments/dev/values.yaml --dry-run

# Real apply (ensure you have credentials and helm/kubectl available):
./scripts/kinst apply -f deployments/kinst/environments/dev/installables.yaml -v deployments/kinst/environments/dev/values.yaml
```

Secrets and credentials
-----------------------
- Do NOT commit secrets to git. Use CI secret injection or environment variables.
- For OCI registries, set env vars `KINST_HELM_REGISTRY_USERNAME` and `KINST_HELM_REGISTRY_PASSWORD` or provide `repositoryCredentials` at runtime via a values override.

CI tips
-------
- Add a job that runs `kinst plan` and `kinst apply --dry-run` for every PR to validate manifests and versions.
- Inject secret-backed `values-overrides.yaml` in CI to provide registry credentials and other secrets.

Credentials from values.yaml
----------------------------
Prefer keeping credentials in `values.yaml` (injected at runtime) and reference them from `installables.yaml` using `usernamePath`/`passwordPath`. Example:

`deployments/kinst/environments/dev/values.yaml`:
```yaml
registries:
	ghcr:
		username: ${{ secrets.GHCR_USER }}
		password: ${{ secrets.GHCR_PASS }}
```

`deployments/kinst/environments/dev/installables.yaml`:
```yaml
installables:
	- id: private-tool
		type: helm
		name: mychart
		release: mychart
		repository: "oci://ghcr.io/myorg"
		repositoryCredentials:
			usernamePath: registries.ghcr.username
			passwordPath: registries.ghcr.password
```

At runtime kinst resolves the dotted paths into values and performs an OCI `helm registry login` before installing.


# kubectl-label installables

`kubectl-label` is a small installable type you can add to `installables.yaml` to apply one or more labels to a namespace.

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
- Boolean label values are normalized to lowercase strings (`"true"`/`"false"`) by the CLI before calling kubectl.

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

More
----
If you'd like, I can add GitHub Actions snippets showing how to run these steps and inject secrets.
