
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

## Quick start — use the wrapper (recommended)

The supported and recommended way to run the Ansible-based installer is via the
convenience wrapper script `deployments/ansible/run-install.sh`. The wrapper
performs helpful path resolution for environment/secret files, uses `uv` to run
`ansible-playbook` in a controlled venv when available, and performs some
pre-checks (including a Helm v4 compatibility check).

Examples (wrapper):

```bash
# Development (full dev configuration)
deployments/ansible/run-install.sh --env dev

# Minimal dev (no auth)
deployments/ansible/run-install.sh --env minimal

# OpenShift / OCP
deployments/ansible/run-install.sh --env ocp

# Pass extra ansible-playbook args after `--`
deployments/ansible/run-install.sh --env dev -- --check --tags debug_vars
```

See the script `deployments/ansible/run-install.sh --help` for all options and
examples of how the wrapper builds the `ansible-playbook` command.

## Key files

- `installer-playbook.yml` - the entry-point playbook (loads `default_values.yaml`).
- `default_values.yaml` - baseline variable and chart configuration.
- `collections-reqs.yml` - Ansible collections required by the playbook.
- `roles/kagenti_installer/` - role that implements installation logic (variable
   resolution, kind handling, helm operations).
- `deployments/envs/` - example environment value files (dev, minimal, ocp, and
   a secrets example file).

## Prerequisites

- Ansible (minimum supported version: 2.10+; for OpenShift/OCP environments, Ansible 2.12+ is required).
- Python dependencies for Kubernetes support: `PyYAML`, `kubernetes`, `openshift`.
- A working `kubectl` and `helm`.
  - IMPORTANT: This installer and the Ansible `kubernetes.core` collection are
    compatible with Helm v3.x. Helm v4 introduces breaking changes that are
    incompatible with the collection's current Helm integration. Ensure `helm`
    on your PATH is v3.x before running the playbook or the wrapper.
- Install Ansible collections used by the playbook:

   ansible-galaxy collection install -r deployments/ansible/collections-reqs.yml

- Recommended: install the `helm-diff` plugin for cleaner diffs:

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


## Advanced: running Ansible directly (for CI or custom environments)

If you prefer to run `ansible-playbook` directly (for example from a CI job or
when you manage Python deps yourself), the playbook supports direct execution.
When running directly you are responsible for ensuring the right Python
environment, Ansible collections, and `helm` version are available on the
runner.

Checklist when running `ansible-playbook` directly:
- Install Python deps: `pip install PyYAML kubernetes openshift`
- Install Ansible collections: `ansible-galaxy collection install -r deployments/ansible/collections-reqs.yml`
- Optionally set the interpreter: `export ANSIBLE_PYTHON_INTERPRETER=$(which python)`
- Ensure `helm` is v3.x (Helm v4 is incompatible with the Ansible Helm module).

Example (direct invocation):

```bash
ansible-playbook -i localhost, -c local deployments/ansible/installer-playbook.yml \
  -e '{"global_value_files":["../envs/dev_values.yaml"], "secret_values_file": "../envs/.secret_values.yaml"}'
```

When running directly, prefer JSON/YAML `-e` forms to avoid shell-quoting issues.

If you want the wrapper behavior but without `run-install.sh`, replicate the
wrapper's checks in your invocation: resolve relative paths to absolute ones
and pass the merged extra-vars as JSON to `-e`.

If you are using Rancher Desktop follow [these steps](#installation-using-rancher-desktop-on-macos).

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

### Setting UI Image Tags

For OpenShift and other deployments, the Ansible installer automatically determines the latest tag from the GitHub repository and sets it for both the frontend and backend UI images. This ensures you're always using the correct version that matches your Kagenti release.

If you need to override this behavior and use a specific version, you can add the following to your override file or environment values file:

```yaml
charts:
  kagenti:
    values:
      ui:
        frontend:
          tag: "v0.5.0"  # Replace with your desired version
        backend:
          tag: "v0.5.0"  # Replace with your desired version

## Notes / tips
- Chart paths referenced in the values are relative to the `deployments/ansible`
   directory by default. If you change repository layout, update the chart
   `chart:` entries in your value files.
- The role exposes many small knobs in `default_values.yaml` (Kind behavior,
   preload lists, chart `values:` overrides). Inspect that file to discover the
   defaults before overriding.
```

## Installation using Rancher Desktop on MacOS

To ensure Kagenti installs correctly, configure Rancher Desktop with the following settings:

---

### 1. Perform a Factory Reset (if needed)
- Navigate to **Troubleshooting → Factory Reset**.
- After restarting:
  - **Important: disable the default Kubernetes cluster**:
    - Go to **Preferences → Kubernetes** and uncheck **Enable Kubernetes**.
  - Under **Preferences → Container Engine**, select **dockerd** as the container engine.

---

### 2. Update Rancher Desktop to Version 1.21
- This version resolves DNS issues for Kind (UDP port forwarding on Linux/macOS) and supports **VZ virtualization with Rosetta emulation**.
- Download from: [Rancher Desktop v1.21 Release](https://github.com/rancher-sandbox/rancher-desktop/releases/tag/v1.21.0)

---

### 3. Increase Resource Limits
- Kind clusters on Rancher Desktop may fail if Linux inotify limits are too low. Inside the Rancher Desktop VM, ensure:
  ```bash
  sudo sysctl fs.inotify.max_user_watches=524288
  sudo sysctl fs.inotify.max_user_instances=512
  ```
  To make these persistent, add them to `/etc/sysctl.conf` inside the VM.

---

### 4. Configure Virtual Machine Settings
- Go to **Preferences → Virtual Machine → Hardware tab**:
  - Set **Memory** to **16 GB**.
  - Set **CPU** to **4 cores**.
- Switch to the **Emulation tab**:
  - Set **Virtual Machine Type** to **VZ**.
  - Enable **Rosetta Support** under **VZ Options**.




