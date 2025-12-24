# Developer's Guide

## Developer Personas in Kagenti

This guide covers development workflows for multiple personas in the Kagenti ecosystem. Depending on your role, different sections will be more relevant:

- **Agent Developers** → Focus on agent development and A2A protocol integration
- **Tool Developers** → Emphasize MCP tool creation and gateway integration  
- **Extensions Developers** → Custom operators and platform extensions
- **MCP Gateway Operators** → Protocol routing and Envoy configuration

**👥 [Review Complete Personas Documentation](../PERSONAS_AND_ROLES.md#1-developer-personas)** to identify your primary role.

## Working with Git

### Setting up your local repo

1. Create a [fork of kagenti](https://github.com/kagenti/kagenti/fork)

2. Clone your fork – command only shown for HTTPS; adjust the URL if you prefer SSH

```shell
git clone https://github.com/<your-username>/kagenti.git
cd kagenti
```

3. Add the upstream repository as a remote (adjust the URL if you prefer SSH)

```shell
git remote add upstream https://github.com/kagenti/kagenti.git
```

4. Fetch all tags from upstream

```shell
git fetch upstream --tags
```

### Pre-commit

This project leverages [pre-commit](https://pre-commit.com/) to enforce consistency in code style and run checks prior to commits with linters and formatters.

Installation can be done via [directions here](https://pre-commit.com/#installation) or `brew install pre-commit` on MacOS.

From the project base, this will install the Git hook:
```sh
pre-commit install
```

To run against all files manually:
```sh
pre-commit run --all-files
```

VSCode extensions such as this [pre-commit-helper](https://marketplace.visualstudio.com/items?itemName=elagil.pre-commit-helper) can be configured to run directly when files are saved in VSCode.

### Making a PR

Work on your local repo cloned from your fork. Create a branch:

```shell
git checkout -b <name-of-your-branch>
```

When ready to make your PR, make sure first to rebase from upstream
(things may have changed while you have been working on the PR):

```shell
git checkout main; git fetch upstream; git merge --ff-only upstream/main
git checkout <name-of-your-branch>
git rebase main
```

Resolve any conflict if needed, then you can make your PR by doing:

```shell
git commit -am "<your commit message>" -s
```

Note that commits must be all signed off to pass DCO checks.
It is reccomended (but not enforced) to follow best practices
for commits comments such as [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/).

Push the PR:

```shell
 git push --set-upstream origin <name-of-your-branch>
 ```

 Open the URL printed by the git push command for the PR and complete the PR by
 entering all the required info - pay attention to the type of PR indicator that goes
 at the start of the title, a meaningful description of what the PR does
 and possibly which issue is neing fixed.


### Tagging and triggering a build for new tag

Note - this is only enabled for maintainers for the project.

Checkout `main` and make sure it equals `main` in the upstream repo as follows:

if working on a fork and "upstream" is the name of the upstream remote (commmon convention)

```shell
git checkout main; git fetch upstream; git merge --ff-only upstream/main
```

if a maintainer using a branch upstream directly (not reccomended)

```shell
git checkout main; git pull
```

check existing tags e.g.,

```shell
git tag
v0.0.1-alpha.1
v0.0.2-alpha.1
...
v0.0.4-alpha.9
```

create a new tag e.g.

```shell
git tag v0.0.4-alpha.10
```

Push the tag upstream

```shell
git push upstream v0.0.4-alpha.10
```

## Kagenti UI Development

The Kagenti UI v2 is a modern web application consisting of two components:
- **Frontend**: React + TypeScript application with PatternFly components
- **Backend**: FastAPI REST API that interfaces with Kubernetes

### Running Locally

#### Prerequisites

- **Frontend**: Node.js 20+ and npm
- **Backend**: Python 3.11+ and uv (package manager)
- Access to a Kubernetes cluster with kubeconfig properly configured

#### Backend Development Server

1. Navigate to the backend directory:

    ```shell
    cd kagenti/backend
    ```

2. Create virtual environment and install dependencies:

    ```shell
    uv venv
    source .venv/bin/activate
    uv pip install -e .
    ```

3. Run the development server:

    ```shell
    uvicorn app.main:app --reload --port 8000
    ```

The backend API will be available at `http://localhost:8000` with:
- Swagger UI docs: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

#### Frontend Development Server

1. Navigate to the frontend directory:

    ```shell
    cd kagenti/ui-v2
    ```

2. Install dependencies:

    ```shell
    npm install
    ```

3. Start the development server:

    ```shell
    npm run dev
    ```

The frontend will be available at `http://localhost:3000`. It automatically proxies API requests to the backend at `http://localhost:8000`.

**Note**: When running locally, you can explore UI features. To connect to agents or tools, you'll need to expose them via HTTPRoutes in your Kubernetes cluster.

### Building and Loading Images for Kubernetes Testing

The project Makefile provides convenient targets for building and loading images into your Kind cluster for testing.

#### Build Both Frontend and Backend Images

```shell
make build-load-ui
```

This command will:
1. Build both frontend and backend Docker images with auto-generated tags
2. Load them into your Kind cluster (default: `kagenti`)
3. Display the Helm upgrade command to deploy your images

#### Build Individual Images

Build only the frontend:
```shell
make build-load-ui-frontend
```

Build only the backend:
```shell
make build-load-ui-backend
```

#### Custom Tags and Cluster Names

Override default values:
```shell
make build-load-ui UI_FRONTEND_TAG=my-feature UI_BACKEND_TAG=my-feature KIND_CLUSTER_NAME=my-cluster
```

### Updating Your Kubernetes Deployment

After building and loading your images, update your Kagenti installation with the new image tags:

```shell
helm upgrade --install kagenti charts/kagenti \
  --namespace kagenti-system \
  --set openshift=false \
  --set ui.frontend.image=ghcr.io/kagenti/kagenti-ui-v2 \
  --set ui.frontend.tag=<your-frontend-tag> \
  --set ui.backend.image=ghcr.io/kagenti/kagenti-backend \
  --set ui.backend.tag=<your-backend-tag> \
  -f <your-values-file>
```

**Tip**: The `make build-load-ui` command displays the exact Helm command with your generated tags. Copy and paste it from the output.

Once the upgrade completes, access the UI at `http://kagenti-ui.localtest.me:8080`.

### Quick Development Workflow

1. Make changes to frontend or backend code
2. Run `make build-load-ui` to build and load both images
3. Copy the displayed Helm upgrade command and run it
4. Wait for pods to restart with new images
5. Test your changes at `http://kagenti-ui.localtest.me:8080`

### Environment Variables Import Feature

The Kagenti UI supports importing environment variables from local `.env` files or remote URLs when creating agents. This feature simplifies agent configuration by allowing reuse of standardized environment variable definitions.

#### Supported Formats

**Standard .env Format**:
```env
MCP_URL=http://weather-tool:8080/mcp
LLM_MODEL=llama3.2
PORT=8000
```

**Extended Format with Kubernetes References**:

When referencing values from Kubernetes Secrets or ConfigMaps, use JSON format enclosed in single quotes:

```env
# Standard direct values
PORT=8000
MCP_URL=http://weather-tool:8080/mcp
LOG_LEVEL=INFO

# Secret reference - JSON format in single quotes
OPENAI_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'

# ConfigMap reference - JSON format in single quotes
APP_CONFIG='{"valueFrom": {"configMapKeyRef": {"name": "app-settings", "key": "config.json"}}}'
```

**Format Requirements for JSON References:**
- Entire JSON must be in **single quotes** (`'...'`)
- Use **double quotes** for JSON keys and values
- No spaces around the `=` sign
- Valid JSON structure: `{"valueFrom": {"secretKeyRef": {"name": "...", "key": "..."}}}`
- Or for ConfigMaps: `{"valueFrom": {"configMapKeyRef": {"name": "...", "key": "..."}}}`

**Important:**
- The Secret/ConfigMap must exist in the agent's namespace
- The agent needs permission to read the referenced resources
- Mix standard values and references in the same file

#### How to Use

1. **Navigate** to the Import New Agent page
2. **Expand** the "Environment Variables" section
3. **Click** "Import from File/URL" button
4. **Choose** import method:
   - **Upload File**: Drag and drop or browse for a local `.env` file
   - **From URL**: Enter a URL to a remote `.env` file (e.g., from GitHub)
5. **Review** the parsed variables in the preview
6. **Click** "Import" to add variables to your agent configuration
7. **Edit** or **delete** variables as needed before creating the agent

#### Variable Types

When adding or editing environment variables, you can choose from three types:

- **Direct Value**: Simple key-value pair (e.g., `PORT=8000`)
- **Secret**: Reference to a Kubernetes Secret (requires secret name and key)
- **ConfigMap**: Reference to a Kubernetes ConfigMap (requires configMap name and key)

The UI provides conditional form fields based on the selected type, making it easy to configure the appropriate values.

#### Example URLs

Import environment variables directly from agent example repositories:

```
https://raw.githubusercontent.com/kagenti/agent-examples/main/a2a/git_issue_agent/.env.openai
https://raw.githubusercontent.com/kagenti/agent-examples/main/a2a/weather_service/.env
```

### Additional Resources

- Frontend README: `kagenti/ui-v2/README.md`
- Backend README: `kagenti/backend/README.md`
- Makefile UI targets: Run `make help-ui` for details
- Environment Variables Import Design: `docs/env-import-feature-design.md`


