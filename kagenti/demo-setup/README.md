# Demo Setup Scripts

This directory contains an automated setup script for quickly deploying Kagenti demos after a fresh installation.

## Overview

The `deploy.py` script automates the deployment of demo agents and tools, making it easy to:
- Recreate demos after deleting and recreating Kagenti installations
- Quickly set up demo environments for development and testing
- Ensure consistent demo configurations across deployments
- Automatically configure Keycloak for authentication and authorization

## Component YAML Files
The setup script uses pre-configured Component YAML files located in the `components/` directory:

- `weather-tool.yaml`: Weather MCP Tool component definition
- `weather-service-agent.yaml`: Weather Service Agent component definition
- `slack-tool.yaml`: Slack MCP Tool component definition
- `slack-researcher-agent.yaml`: Slack Research Agent component definition

## Prerequisites

Before running the setup script, ensure:

1. **Kagenti is installed**: Follow the [installation guide](../../docs/demos.md#installation)
2. **kubectl is configured**: Can connect to your Kubernetes cluster
3. **Namespace exists**: The target namespace must be created (done by installer)
   ```bash
   kubectl get namespace team1
   ```
4. **Install dependencies for auth setup:**
   ```bash
   cd kagenti/demo-setup/
   source ./install.sh
   ```
5. **For Slack demo**: Set `SLACK_BOT_TOKEN` and `ADMIN_SLACK_BOT_TOKEN` in `.env` before installing Kagenti
6. **For Weather demo**: Ollama running with required model

## Usage

### Script Command
```bash
python3 deploy.py [--demo {weather,slack,all}] [--namespace NAMESPACE]
```

**Options:**
- `--demo {weather,slack,all}`: Which demo to setup (default: all)
- `--namespace NAMESPACE`: Kubernetes namespace to deploy to (default: team1)
- `--help`: Show help message

### Quick Start

**Setup all demos (weather + slack):**
```bash
python3 deploy.py
```

**Setup only weather demo:**
```bash
python3 deploy.py --demo weather
```

**Setup only slack demo:**
```bash
python3 deploy.py --demo slack
```

**Custom namespace:**
```bash
python3 deploy.py --demo all --namespace team2
```

### Verify Deployment

Check deployment status:

```bash
# Check pods
kubectl get pods -n team1

# Check component status
kubectl get components -n team1

# View logs
kubectl logs -f deployment/weather-tool -n team1
kubectl logs -f deployment/weather-service -n team1
kubectl logs -f deployment/slack-tool -n team1
kubectl logs -f deployment/slack-researcher -n team1
```

## Cleanup

To remove the deployed components:

```bash
# Delete weather components
kubectl delete component weather-tool weather-service -n team1

# Delete slack components
kubectl delete component slack-tool slack-researcher -n team1

# Or delete all components
kubectl delete component --all -n team1
```

## Development

### Adding New Demos

To add a new demo:

1. Create component YAML files in `components/` directory
2. Add the demo to `get_demo_components()` function in `deploy.py`
3. Update this README with demo-specific instructions
4. Test with a fresh Kagenti installation

### Exporting Running Components

To export components from a running cluster:

```bash
# Export to YAML
kubectl get component <component-name> -n <namespace> -o yaml > components/<component-name>.yaml

# Clean up for reuse (remove runtime fields)
# Edit the file to remove:
# - metadata.creationTimestamp
# - metadata.resourceVersion
# - metadata.uid
# - metadata.generation
# - metadata.finalizers
# - status section
```

## Troubleshooting

### Namespace doesn't exist

```
Error: Namespace 'team1' does not exist
```

**Solution:** Create the namespace or use an existing one:
```bash
kubectl create namespace team1
# or
python3 deploy.py --namespace <existing-namespace>
```

### Auth demo setup fails

If the Keycloak configuration fails:

**Solution:** Run it manually:
```bash
cd ../auth/auth_demo
pip install -r requirements.txt
export NAMESPACE=team1
export KEYCLOAK_URL="http://keycloak.localtest.me:8080"
export KEYCLOAK_REALM=master
export KEYCLOAK_ADMIN_USERNAME=admin
export KEYCLOAK_ADMIN_PASSWORD=admin
python3 set_up_demo.py
```

### Deployments not ready

If deployments take longer than expected:

1. Check pod status:
   ```bash
   kubectl get pods -n team1
   ```

2. Check events:
   ```bash
   kubectl get events -n team1 --sort-by='.lastTimestamp'
   ```

3. Check pod logs:
   ```bash
   kubectl logs <pod-name> -n team1
   ```

### Components already exist

If components already exist, the script will update them:
```bash
# To start fresh, delete existing components first:
kubectl delete component weather-tool weather-service slack-tool slack-researcher -n team1
```

