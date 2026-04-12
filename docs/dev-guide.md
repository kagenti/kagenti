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

From the project base, install both the pre-commit and commit-msg hooks:
```sh
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

The `pre-commit` hooks run linters and formatters before each commit. The
`commit-msg` hook automatically rewrites AI `Co-authored-by` trailers to
`Assisted-By` so that AI tools don't inflate GitHub contributor stats (see
[Commit Attribution Policy](../CLAUDE.md#commit-attribution-policy)).

To run the pre-commit hooks against all files manually:
```sh
pre-commit run --all-files
```

VSCode extensions such as this [pre-commit-helper](https://marketplace.visualstudio.com/items?itemName=elagil.pre-commit-helper) can be configured to run directly when files are saved in VSCode.

### Feature Flags

All new features **must** be gated behind a feature flag that defaults to
**disabled**. This is a hard requirement — PRs that introduce user-visible
functionality without a flag will be asked to add one.

**How to add a flag:**

1. Add `kagenti_feature_flag_<name>: bool = False` to
   `kagenti/backend/app/core/config.py` with a descriptive comment.
2. Add the flag to `FeatureFlagsResponse` in `kagenti/backend/app/routers/config.py`
   so the frontend can read it.
3. Guard module loading in `kagenti/backend/app/main.py` using the existing
   conditional import pattern.
4. Enable via environment variable: `KAGENTI_FEATURE_FLAG_<NAME>=true`.

See [CLAUDE.md — Feature Flags](../CLAUDE.md#feature-flags-required) for the
full policy and current flag inventory.

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

## HyperShift Development and Testing

HyperShift enables rapid testing of Kagenti on OpenShift by creating ephemeral hosted clusters (sandboxes) where the control plane runs as pods on a management cluster and workers run in AWS. This approach is faster and more cost-effective than deploying full OpenShift clusters.

### Why HyperShift?

- **Fast cluster creation**: 10-15 minutes vs. 45 minutes for IPI
- **Cost efficient**: Ephemeral clusters for testing, destroyed after use
- **OpenShift validation**: Test platform features on real OpenShift (OCP 4.20, 4.21)
- **Parallel testing**: Multiple developers can create isolated test clusters
- **CI/CD integration**: Automated E2E testing on OpenShift via GitHub Actions

### Architecture Overview

```
┌─────────────────────────────────────────────┐
│  HyperShift Management Cluster (OpenShift)  │
│  - Runs hosted cluster control planes       │
│  - MCE 2.10 + HyperShift operator           │
│  - Managed by platform team                 │
│  └─────────────────────────────────────────┘
         │
         ├─► Hosted Cluster 1 (Your Test Cluster)
         │   - Control plane: Pods on mgmt cluster
         │   - Workers: EC2 instances in AWS
         │
         └─► Hosted Cluster 2 (Another Developer)
             - Isolated namespace and AWS resources
```

### Prerequisites

Before creating hosted clusters, you need:

1. **Credentials Package** from the platform team containing:
   - AWS credentials (IAM user for cluster creation)
   - Management cluster kubeconfig (base64-encoded)
   - Base domain and OIDC S3 bucket details

2. **Required Tools**:
   - AWS CLI configured
   - kubectl and oc CLI
   - jq for JSON processing
   - Ansible (installed automatically by setup script)

### Setting Up HyperShift Credentials

#### Option 1: Using Credential Package (Recommended)

If you received a credential package (`.tar.gz` file) from the platform team:

```bash
# Extract the package
tar -xzf <package-name>.tar.gz
cd <package-name>

# Source the credentials
source .env.<tag>

# Verify setup
echo $MANAGED_BY_TAG
oc whoami --show-server  # Should show management cluster API
```

The `.env` file automatically creates the management cluster kubeconfig at `~/.kube/<tag>-mgmt.kubeconfig` if it doesn't exist.

#### Option 2: Manual Setup

If setting up from scratch, run the credential setup script:

```bash
cd kagenti

# Set your managed-by tag (identifies your resources)
export MANAGED_BY_TAG="your-name-dev"

# Run setup (requires logged in to AWS and management cluster)
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# Source the generated credentials
source .env.${MANAGED_BY_TAG}
```

This creates:
- AWS IAM users with scoped permissions
- OpenShift service account on management cluster
- Local `.env.${MANAGED_BY_TAG}` file with all credentials

### Creating a Hosted Cluster

Once credentials are configured, create a test cluster:

```bash
# Navigate to repository root
cd kagenti

# Create cluster with random suffix
./.github/scripts/hypershift/create-cluster.sh

# Or specify a custom suffix
./.github/scripts/hypershift/create-cluster.sh my-test

# Keep cluster after creation (skip auto-destroy)
./.github/scripts/hypershift/create-cluster.sh my-test --skip-cluster-destroy
```

**What happens:**
1. Creates AWS infrastructure (VPC, subnets, security groups)
2. Creates HostedCluster CR on management cluster
3. Waits for control plane pods to be ready
4. Creates worker NodePool (2x m5.xlarge by default)
5. Waits for cluster to become accessible
6. Outputs kubeconfig path

**Cluster naming:**
- Format: `${MANAGED_BY_TAG}-<suffix>`
- Example: `my-team-my-test`
- Must be ≤32 characters (AWS IAM role name limit)

**Default configuration:**
- OpenShift version: 4.20 (or `OCP_VERSION` env var)
- Workers: 2 nodes (m5.xlarge)
- Region: us-east-1
- Namespace: `${MANAGED_BY_TAG}` on management cluster

### Running Tests on HyperShift

After creating a cluster, run the full E2E test suite:

```bash
# Run full test (deploy Kagenti + E2E tests)
./.github/scripts/local-setup/hypershift-full-test.sh <cluster-suffix> --skip-cluster-destroy

# Re-run tests on existing cluster (skip cluster creation)
./.github/scripts/local-setup/hypershift-full-test.sh <cluster-suffix> --skip-cluster-create --skip-cluster-destroy

# Deploy Kagenti only (no tests)
./.github/scripts/hypershift/deploy-kagenti.sh <cluster-suffix>
```

**Test workflow:**
1. Sets up kubeconfig for hosted cluster
2. Deploys Kagenti platform via Ansible
3. Runs E2E test suite (`kagenti/tests/e2e/`)
4. Optionally destroys cluster after tests

**Working with kubeconfig:**

```bash
# Kubeconfig is saved to standard location
export KUBECONFIG=~/hypershift-clusters/${MANAGED_BY_TAG}-<suffix>/kubeconfig

# Or use the helper to find it
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=$(find ~/hypershift-clusters -name "kubeconfig" | grep ${MANAGED_BY_TAG}-<suffix>)

# Verify access
oc get nodes
oc get co  # Check cluster operators
```

### Destroying a Hosted Cluster

When finished testing, clean up resources:

```bash
# Destroy specific cluster
./.github/scripts/hypershift/destroy-cluster.sh <cluster-suffix>

# Or use full-test script with destroy flag
./.github/scripts/local-setup/hypershift-full-test.sh <cluster-suffix> --include-cluster-destroy
```

**What gets deleted:**
- HostedCluster CR and control plane pods
- Worker NodePool and EC2 instances
- AWS VPC, subnets, NAT gateways, load balancers
- IAM roles and instance profiles

**Important:** Cluster destruction can take 10-20 minutes. Monitor progress:

```bash
# Watch HostedCluster deletion
oc get hostedcluster -n ${MANAGED_BY_TAG} -w

# Check for stuck resources
oc get hostedcluster -n ${MANAGED_BY_TAG} -o yaml | grep finalizers -A 5
```

### Cost Management

Hosted clusters incur AWS costs while running:

**Per cluster (running):**
- 2x m5.xlarge workers: ~$0.38/hour (~$277/month if left running)
- VPC/networking: ~$0.10/hour
- EBS volumes: ~$0.10/GB/month

**Best practices:**
- Destroy clusters when not in use (evenings, weekends)
- Use `--skip-cluster-destroy` only during active development
- Monitor AWS costs via `aws ce get-cost-and-usage` or AWS Console
- Tag all resources with `kagenti.io/managed-by` for tracking

### Troubleshooting

#### Cluster Creation Fails

```bash
# Check HostedCluster status
oc get hostedcluster -n ${MANAGED_BY_TAG}
oc describe hostedcluster ${MANAGED_BY_TAG}-<suffix> -n ${MANAGED_BY_TAG}

# Check control plane pods
oc get pods -n ${MANAGED_BY_TAG}-<suffix>

# Check HyperShift operator logs
oc logs -n hypershift deployment/operator -f
```

#### Workers Not Ready

```bash
# Check NodePool status
oc get nodepool -n ${MANAGED_BY_TAG}
oc describe nodepool ${MANAGED_BY_TAG}-<suffix> -n ${MANAGED_BY_TAG}

# Check AWS EC2 instances (requires AWS credentials)
aws ec2 describe-instances --filters "Name=tag:kubernetes.io/cluster/${MANAGED_BY_TAG}-<suffix>,Values=owned"
```

#### Cleanup Issues

If cluster destruction hangs, manually remove finalizers:

```bash
# Remove finalizers from HostedCluster
oc patch hostedcluster ${MANAGED_BY_TAG}-<suffix> -n ${MANAGED_BY_TAG} \
  --type=merge -p '{"metadata":{"finalizers":[]}}'

# Force delete if needed
oc delete hostedcluster ${MANAGED_BY_TAG}-<suffix> -n ${MANAGED_BY_TAG} --force --grace-period=0
```

See [CLEANUP-TEST-RESULTS.md](../CLEANUP-TEST-RESULTS.md) for detailed cleanup findings.

### CI/CD Integration

The repository includes GitHub Actions workflows for automated HyperShift testing:

- `.github/workflows/e2e-hypershift.yaml` - OpenShift 4.20 testing
- `.github/workflows/e2e-hypershift-4.21.yaml` - OpenShift 4.21 testing (manual trigger)

**Workflow features:**
- Automatic cluster creation and cleanup
- Slot-based parallelism (max 3 concurrent clusters)
- Full E2E test suite execution
- Artifact upload for debugging

### Advanced Topics

#### Management Cluster Setup

For platform administrators deploying new management clusters, see:

- [Terraform Management Cluster Guide](../terraform/README.md) - Complete deployment workflow
- [Architecture Overview](../ARCHITECTURE-4.21.md) - Dual cluster strategy and design decisions
- [Quick Start Guide](../QUICKSTART-4.21.md) - Step-by-step deployment (90 minutes)

#### Customizing Hosted Clusters

Modify cluster configuration by setting environment variables before creation:

```bash
# Use different OpenShift version
export OCP_VERSION=4.21

# Change worker instance type and count
export INSTANCE_TYPE=m5.2xlarge
export WORKER_COUNT=3

# Use different AWS region
export AWS_REGION=us-west-2

# Create cluster with custom settings
./.github/scripts/hypershift/create-cluster.sh custom
```

#### Multiple Hosted Clusters

You can run multiple hosted clusters simultaneously:

```bash
# Create first cluster
./.github/scripts/hypershift/create-cluster.sh dev1 --skip-cluster-destroy

# Create second cluster (different suffix)
./.github/scripts/hypershift/create-cluster.sh dev2 --skip-cluster-destroy

# List all your clusters
oc get hostedcluster -n ${MANAGED_BY_TAG}
```

Each cluster gets isolated AWS resources and namespace on the management cluster.

### Additional Resources

- [HyperShift Documentation](https://hypershift-docs.netlify.app/) - Official HyperShift docs
- [MCE Documentation](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/2.10/html/multicluster_engine/multicluster_engine_overview) - MultiCluster Engine overview
- [Credential Setup Script](../.github/scripts/hypershift/setup-hypershift-ci-credentials.sh) - Detailed script documentation
- [Cleanup Test Results](../CLEANUP-TEST-RESULTS.md) - Known cleanup issues and workarounds


