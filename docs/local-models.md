# Using Local Models with Kagenti

Kagenti supports any OpenAI-compatible model backend. This guide covers using [Ollama](https://ollama.com/) to run LLM models locally, eliminating the need for an external API key.

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Kind (Local Development)](#kind-local-development)
- [OpenShift](#openshift)
- [Tested Models](#tested-models)
- [Troubleshooting](#troubleshooting)

---

## Overview

Kagenti agents use three environment variables to configure their LLM backend:

| Variable | Description | Example (Ollama) | Example (OpenAI) |
|----------|-------------|------------------|-------------------|
| `LLM_API_BASE` | API endpoint URL | `http://host.docker.internal:11434/v1` | `https://api.openai.com/v1` |
| `LLM_API_KEY` | API key | `dummy` (Ollama ignores this) | Your OpenAI API key |
| `LLM_MODEL` | Model identifier | `qwen2.5:3b` | `gpt-4o-mini-2024-07-18` |

When deploying agents through the Kagenti UI, you select an **environment variable set** (`ollama` or `openai`) that populates these values automatically. No code changes are needed to switch between backends.

## How It Works

Kagenti pre-configures two environment variable sets in each agent namespace via a ConfigMap:

- **`ollama`** - Points to a local Ollama instance with a default model
- **`openai`** - Points to the OpenAI API using credentials from the `openai-secret`

These are defined in the `environments` ConfigMap (see `charts/kagenti/templates/agent-namespaces.yaml`). When you import an agent through the UI, you choose which environment set to apply.

---

## Kind (Local Development)

On Kind clusters, Ollama runs on the host machine and agents access it through Docker networking.

### Prerequisites

1. Install Ollama: <https://ollama.com/download>
2. Pull a model:

   ```bash
   ollama pull qwen2.5:3b
   ```

3. Start Ollama (listening on all interfaces):

   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```

### Agent Configuration

The default `ollama` environment set points to `http://host.docker.internal:11434/v1`, which resolves to the host machine from inside Docker/Kind containers. No additional configuration is needed.

When importing an agent in the UI, select the **ollama** environment variable set.

### Automated Setup

The Kind full-test script handles Ollama installation and model pulling automatically:

```bash
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy
```

This runs the `50-install-ollama.sh` and `60-pull-ollama-model.sh` scripts, which install Ollama and pull `qwen2.5:3b`.

---

## OpenShift

On OpenShift, Ollama cannot run on the host machine since agents run in a remote cluster. There are two approaches:

### Option 1: Deploy Ollama as a Pod (Recommended)

Deploy Ollama as a Kubernetes Deployment within the cluster so agents can reach it over the cluster network.

1. **Create the Ollama Deployment:**

   ```bash
   kubectl apply -n kagenti-system -f - <<'EOF'
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: ollama
     labels:
       app: ollama
   spec:
     replicas: 1
     selector:
       matchLabels:
         app: ollama
     template:
       metadata:
         labels:
           app: ollama
       spec:
         containers:
         - name: ollama
           image: ollama/ollama:latest
           ports:
           - containerPort: 11434
           resources:
             requests:
               cpu: "2"
               memory: "8Gi"
             limits:
               cpu: "4"
               memory: "16Gi"
           volumeMounts:
           - name: ollama-data
             mountPath: /root/.ollama
         volumes:
         - name: ollama-data
           emptyDir: {}
   ---
   apiVersion: v1
   kind: Service
   metadata:
     name: ollama
   spec:
     selector:
       app: ollama
     ports:
     - port: 11434
       targetPort: 11434
   EOF
   ```

2. **Pull a model inside the pod:**

   ```bash
   kubectl exec -n kagenti-system deploy/ollama -- ollama pull qwen2.5:3b
   ```

3. **Update the `ollama` environment set** to point to the in-cluster service. Edit the `environments` ConfigMap in each agent namespace (e.g., `team1`):

   ```bash
   kubectl edit configmap environments -n team1
   ```

   Change the `LLM_API_BASE` value from `http://host.docker.internal:11434/v1` to:

   ```
   http://ollama.kagenti-system.svc.cluster.local:11434/v1
   ```

   Or override via Helm values when installing the chart. See [Customizing the Ollama Endpoint](#customizing-the-ollama-endpoint) below.

### Option 2: Use an External Ollama Server

If you have Ollama running on an accessible machine (e.g., a GPU workstation), you can point agents to its external address:

1. Start Ollama on the external machine:

   ```bash
   OLLAMA_HOST=0.0.0.0 ollama serve
   ```

2. Ensure the OpenShift cluster can reach the machine over the network.

3. Update the `ollama` environment set `LLM_API_BASE` to `http://<external-ip>:11434/v1`.

### Resource Considerations for OpenShift

| Model Size | Minimum RAM | Recommended CPU | Notes |
|-----------|-------------|-----------------|-------|
| 3B params (e.g., `qwen2.5:3b`) | 8 Gi | 2 cores | Good for testing and demos |
| 8B params (e.g., `granite3.3:8b`) | 16 Gi | 4 cores | Better quality, tested on Apple M3 with 64 GB RAM |
| 70B+ params | 64+ Gi | 8+ cores | Requires GPU for reasonable performance |

For production OpenShift deployments, consider:
- **GPU nodes**: Use `nvidia.com/gpu` resource requests for significantly better inference speed
- **Persistent storage**: Replace `emptyDir` with a PVC to avoid re-downloading models on pod restart
- **Node affinity**: Schedule the Ollama pod on nodes with adequate memory/GPU resources

### Customizing the Ollama Endpoint

The default `ollama` environment set points to `http://host.docker.internal:11434/v1`, which works for Kind but not for OpenShift. After deploying Kagenti, update the `environments` ConfigMap in each agent namespace to point to your Ollama service:

```bash
# For each agent namespace (e.g., team1, team2)
kubectl get configmap environments -n team1 -o yaml | \
  sed 's|http://host.docker.internal:11434/v1|http://ollama.kagenti-system.svc.cluster.local:11434/v1|' | \
  kubectl apply -f -
```

This updates `LLM_API_BASE` so agents in that namespace reach the in-cluster Ollama service. Repeat for each agent namespace.

---

## Tested Models

The following models have been tested with Kagenti agents:

### Ollama Models

| Model | Size | Tested With | Notes |
|-------|------|-------------|-------|
| `qwen2.5:3b` | 3B | Kind (CI), Apple Silicon | Default model in CI pipeline |
| `llama3.2:3b-instruct-fp16` | 3B | Kind, Apple Silicon | Default in `ollama` environment set |
| `granite3.3:8b` | 8B | Kind, Apple M3 (64 GB) | Tested with Slack Research Agent |
| `ibm/granite4:latest` | varies | Kind | Tested with GitHub Issue Agent |

### OpenAI Models

| Model | Notes |
|-------|-------|
| `gpt-4o-mini-2024-07-18` | Default in `openai` environment set |
| `gpt-4.1-nano` | Lightweight, tested with Slack Research Agent |
| `gpt-4.1-mini` | Tested with Slack Research Agent |
| `gpt-4.1` | Tested with Slack Research Agent |
| `gpt-4o` | Tested with Slack Research Agent |

### Using Other Models

Any model that exposes an OpenAI-compatible API endpoint can be used. This includes:
- [vLLM](https://docs.vllm.ai/)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp)
- [LocalAI](https://localai.io/)

Set `LLM_API_BASE` to the `/v1` endpoint of your model server and `LLM_MODEL` to the model name it serves.

---

## Troubleshooting

### Ollama not reachable from Kind pods

**Symptom**: Agent pods fail to connect to the LLM.

**Cause**: `host.docker.internal` may not resolve on Linux without Docker Desktop.

**Fix**: On Linux with plain Docker, start Ollama on all interfaces and use the host IP:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then check the host gateway IP:

```bash
docker network inspect kind | grep Gateway
```

Update the `LLM_API_BASE` in the ConfigMap to use that gateway IP.

### Model too slow or out of memory

**Symptom**: Agent responses are very slow or the Ollama pod gets OOMKilled.

**Fix**: Use a smaller model (e.g., `qwen2.5:3b` instead of an 8B model) or increase the pod's memory limits.

### Agent uses wrong LLM backend

**Symptom**: Agent tries to call OpenAI instead of Ollama (or vice versa).

**Fix**: When importing an agent in the Kagenti UI, verify you selected the correct environment variable set (`ollama` or `openai`). You can check the running pod's environment:

```bash
kubectl exec -n team1 <agent-pod> -- env | grep LLM_
```
