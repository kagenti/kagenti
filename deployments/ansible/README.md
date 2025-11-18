
# Kagenti Ansible installer

This directory contains an Ansible playbook and role to install Kagenti components
using the `kubernetes.core` Ansible collection (Helm and Kubernetes object support).

The playbook loads a set of default values and can merge per-environment value files
from `deployments/envs`. It can also create a local Kind cluster for development
and preload images when requested.

## What this installer does
- Installs Helm charts listed under the `charts:` section in the merged values.
- Optionally creates a Kind cluster when kubectl cannot reach an API server and
   `create_kind_cluster` is true.
- Loads secret values from a separate secrets file (if provided) and merges them
   into chart values.

## Key files
- `installer-playbook.yml` - the entry-point playbook (loads `default_values.yaml`).
- `default_values.yaml` - baseline variable and chart configuration.
- `collections-reqs.yml` - Ansible collections required by the playbook.
- `roles/kagenti_installer/` - role that implements installation logic (variable
   resolution, kind handling, helm operations).
- `deployments/envs/` - example environment value files (dev, minimal, ocp, and
   a secrets example file).

## Prerequisites
- Ansible (tested with Ansible 2.10+ / 2.12+ depending on your env).
- Python deps for kubernetes support: `PyYAML`, `kubernetes`, `openshift`.
- Install Ansible collections used by the playbook:

   ansible-galaxy collection install -r deployments/ansible/collections-reqs.yml

- A working `kubectl` and Helm (recommended: install `helm-diff` plugin for cleaner diffs):

   helm plugin install https://github.com/databus23/helm-diff

## How variables and value files are resolved
- The playbook loads `default_values.yaml` first. You may supply one or more
   additional environment value files using the `global_value_files` extra-var.
- Paths in `global_value_files` are resolved relative to the playbook directory
   (`deployments/ansible`) unless you pass an absolute path. Example relative
   path: `"../envs/dev_values.yaml"`.
- Secret values are loaded from the variable `secret_values_file`. By default
   the playbook sets `secret_values_file: "../envs/.secret_values.yaml"`.
   The role will resolve relative paths against the playbook directory before
   validating and loading the file.

Important variables you can override (via `-e` / `--extra-vars`):
- `global_value_files` (list) - additional values files to merge, e.g. `["../envs/dev_values.yaml"]`.
- `secret_values_file` (string) - path to a secret values file (absolute or relative to playbook dir).
- `create_kind_cluster` (bool) - when true and kubectl is not reachable, the role will
   attempt to create a Kind cluster (default from `default_values.yaml`).
- `kind_cluster_name`, `kind_images_preload`, `container_engine`, `kind_config`,
   `kind_config_registry`, `preload_images_file` - Kind-related knobs (see `default_values.yaml`).

Notes on overrides: pass extra-vars as JSON to avoid shell quoting issues. For
example:

```
# From repo root using the 'uv' wrapper (keeps paths unmodified):
uv run ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml -e '{"global_value_files":["../envs/dev_values.yaml"],"kind_images_preload":false}'

# Direct with ansible-playbook (recommended: JSON form for complex values):
ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml -e '{"global_value_files":["../envs/dev_values_minimal.yaml"], "secret_values_file": "../envs/.secret_values.yaml"}'

# Absolute path example (works from any cwd):
ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml -e '{"global_value_files":["/full/path/to/kagenti/deployments/envs/ocp_values.yaml"]}'

```

## Environment examples
- Development (full dev configuration): `../envs/dev_values.yaml` (enables UI,
   platform operator, mcpGateway, istio where required).
- Minimal dev (no auth): `../envs/dev_values_minimal.yaml`.
- OpenShift / OCP example: `../envs/ocp_values.yaml`.

Pick one or more of the files in `deployments/envs` and pass them via
`global_value_files`. The playbook merges these files (in order) into the
runtime variables used to decide which charts to install.

## Secrets handling
- Example secrets file: `deployments/envs/secret_values.yaml.example`.
 - Example secrets file: `deployments/envs/secret_values.yaml.example`.
 - Default behavior: if you copy the example to `deployments/envs/.secret_values.yaml`
    (the repository default location) the installer will load it automatically and
    you do not need to pass `-e secret_values_file=...`.
 - The playbook resolves relative paths against the playbook directory
    (`deployments/ansible`) and will load the default secret file if present.
 - To use a different secrets file, pass the path explicitly via extra-vars, for
    example:

    ```bash
    ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml -e '{"secret_values_file": "../envs/my_secrets.yaml"}'
    ```

    Or with the wrapper:

    ```bash
    deployments/ansible/run-install.sh --env ocp --secret ../envs/my_secrets.yaml
    ```

 - Wrapper behavior: the wrapper will warn-and-skip if the default file is
    missing; if you explicitly provide `--secret` and the file is missing the
    wrapper will fail early with an error. The playbook itself also validates
    the resolved path when it is provided.

## Debugging and inspection
- If an extra-var doesn't appear to take effect, prefer the explicit JSON/YAML
   form for `-e` to avoid shell-quoting mistakes.
- Run the playbook with `--tags debug_vars` (or omit `--tags`) to show debug
   output added to the role which prints resolved variable values.

## Running without the `uv` wrapper (quick checklist)
1. Ensure Python deps are installed:

    pip install PyYAML kubernetes openshift

2. Install Ansible collections:

    ansible-galaxy collection install -r deployments/ansible/collections-reqs.yml

3. Optionally set the Python interpreter Ansible should use (the playbook will
    try to use `ANSIBLE_PYTHON_INTERPRETER` env var or a repository virtualenv by
    default):

    export ANSIBLE_PYTHON_INTERPRETER=$(which python)

4. Run the playbook (example):

    ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml -e '{"global_value_files":["../envs/dev_values.yaml"], "secret_values_file": "../envs/.secret_values.yaml"}'

## Wrapper examples (using `run-install.sh`)

Examples:

- Development (full dev configuration):

```bash
deployments/ansible/run-install.sh --env dev
```

- Minimal dev (no auth):

```bash
deployments/ansible/run-install.sh --env minimal
```

- OpenShift / OCP:

```bash
deployments/ansible/run-install.sh --env ocp
```

Notes on passing additional ansible-playbook args:
- Add `--` followed by any `ansible-playbook` options. Example (runs the playbook in check mode and shows resolved variables):

```bash
deployments/ansible/run-install.sh --env dev -- --check --tags debug_vars
```

The wrapper prefers to run `uv run ansible-playbook` when `uv` is available (so `uv` manages the venv/deps); if `uv` is not found it will fall back to `ansible-playbook` with a warning.

## Using override files

Override files must be passed with a path relative to the directory from which you invoke the script (your current working directory). The layout of variables should be the same as
in the value files. For example, to disable the use of service account CA for OCP, create a file
`.values_override.yaml` with this content:

```yaml
charts:
  kagenti:
    values:
      uiOAuthSecret:
        useServiceAccountCA: false
```

Save the file in a place of your choice (for example, `deployments/envs/.values_override.yaml`) and run:

```shell
 ./deployments/ansible/run-install.sh --env ocp --env-file ./deployments/envs/.values_override.yaml
``` 

## Notes / tips
- Chart paths referenced in the values are relative to the `deployments/ansible`
   directory by default. If you change repository layout, update the chart
   `chart:` entries in your value files.
- The role exposes many small knobs in `default_values.yaml` (Kind behavior,
   preload lists, chart `values:` overrides). Inspect that file to discover the
   defaults before overriding.





