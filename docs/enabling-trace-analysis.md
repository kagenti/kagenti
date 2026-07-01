# Enabling the Trace Analysis Feature

The `trace_analysis` feature adds a **Trace Analysis** card to the Observability
page **and** deploys the backing `trace-analysis` component
(`ghcr.io/kagenti/trace-analysis`) into `kagenti-system`. When the flag is on,
the kagenti chart renders the Deployment/Service/Route automatically — no
separate install is required.

Like all Kagenti features, it is gated behind a feature flag that is **off by
default** (see the Feature Flags section of [CLAUDE.md](../CLAUDE.md)).

## How the flag flows through the stack

```
Helm value featureFlags.traceAnalysis
   │
   ├─► env KAGENTI_FEATURE_FLAG_TRACE_ANALYSIS  ─► backend Settings.kagenti_feature_flag_trace_analysis
   ├─► env TRACE_ANALYSIS_DASHBOARD_URL         ─► backend Settings.trace_analysis_dashboard_url
   │
   └─► backend GET /api/v1/config/features   → { ..., "traceAnalysis": true }
       backend GET /api/v1/config/dashboards → { ..., "traceAnalysis": "<url>" }
                                              │
                                              └─► UI useFeatureFlags() / ObservabilityPage renders the card
```

Key files:

| Layer | File |
|-------|------|
| Flag definition | `kagenti/backend/app/core/config.py` (`kagenti_feature_flag_trace_analysis`, `trace_analysis_dashboard_url`) |
| API response | `kagenti/backend/app/routers/config.py`, `kagenti/backend/app/models/responses.py` |
| Helm value | `charts/kagenti/values.yaml` (`featureFlags.traceAnalysis` flag + `traceAnalysis.*` deployment config) |
| Helm wiring | `charts/kagenti/templates/ui.yaml` (ConfigMap key + env vars) |
| Component deploy | `charts/kagenti/templates/trace-analysis.yaml` (Deployment + Service + Route/HTTPRoute, gated on the flag) |
| UI | `kagenti/ui-v2/src/hooks/useFeatureFlags.ts`, `src/pages/ObservabilityPage.tsx` |

> **Important:** because the API response *shape* (the `traceAnalysis` field on
> `FeatureFlagsResponse`) is defined in the backend **code**, setting the Helm
> value or env var alone is **not enough** on a cluster running an older image.
> The backend image must contain the code that knows about the field, otherwise
> the env var is read but silently dropped from the response. **Rebuild the
> images from your branch** whenever the flag code is not yet in the deployed
> image.

## Build prerequisite: docker buildx

`make build-load-ui` runs `docker build --load`, which is a **buildx / BuildKit**
flag. On a stock Docker Desktop install buildx is already present. But if you run
the **Docker CLI against a Podman backend** (common on macOS — `docker` is the
client only, server is Podman), the buildx plugin may be missing and the build
fails with:

```
unknown flag: --load
make: *** [build-load-ui-frontend] Error 125
```

Check and fix once:

```bash
docker buildx version            # if this errors with "unknown command", install it:

brew install docker-buildx
mkdir -p ~/.docker/cli-plugins
ln -sf /opt/homebrew/lib/docker/cli-plugins/docker-buildx ~/.docker/cli-plugins/docker-buildx

docker buildx version            # should now print: github.com/docker/buildx v0.35.0 ...
```

(Alternatively, add `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]`
to `~/.docker/config.json` — the symlink above does the same thing and persists.)

## A. Enable on an existing Kind dev cluster

```bash
cd /path/to/kagenti

# 1. Rebuild + load images from your branch (REQUIRED — the flag's code lives in the image).
#    Needs docker buildx / BuildKit (see "Build prerequisite" above).
make build-load-ui                       # or -frontend / -backend for one side only

# 2. Upgrade the existing release IN ITS NAMESPACE, reusing its values + adding the flag.
helm get values kagenti -n kagenti-system -o yaml > /tmp/current-values.yaml
helm upgrade kagenti charts/kagenti \
  -n kagenti-system \
  -f /tmp/current-values.yaml \
  --set featureFlags.traceAnalysis=true

# 3. Force pods to pick up the new image/env (a ConfigMap-only change does NOT restart pods).
kubectl rollout restart deploy/kagenti-backend deploy/kagenti-ui -n kagenti-system
kubectl rollout status  deploy/kagenti-backend -n kagenti-system

# 4. Verify the API actually reports it (curl is not installed in the pod — use python urllib).
POD=$(kubectl get pods -n kagenti-system -o name | grep backend | head -1)
kubectl exec "$POD" -n kagenti-system -- \
  python3 -c "import urllib.request as u; print(u.urlopen('http://localhost:8000/api/v1/config/features').read().decode())"
# expect: ...,"traceAnalysis":true,...
```

### Gotchas

- **Do not** run `helm upgrade --install kagenti charts/kagenti --set featureFlags.traceAnalysis=true`
  on its own. It targets the default namespace and drops the existing release
  values, which trips the guard:
  `mcpGateway.openshiftDomain is required on OpenShift`. Always pass
  `-n kagenti-system` and `-f <current-values>`.
- **Do not** trust a "rollout succeeded" message after only a ConfigMap change.
  The env is injected via `configMapKeyRef`, so the pod template hash does not
  change and pods are not restarted. Use `kubectl rollout restart`.
- The backend pod has **no `curl`**. Use `python3 -c "import urllib.request..."`
  to hit the API from inside the pod.
- **The locally built images are not the tag the chart references.**
  `make build-load-ui` tags images like
  `ghcr.io/kagenti/kagenti-backend:<gitsha>-<timestamp>`, while the deployed
  chart points at a release tag (e.g. `…/kagenti/backend:v0.7.0-alpha.3`). So a
  `helm upgrade` that only flips the flag will **not** switch pods to your newly
  built code. Either build images tagged to match the chart's image values, or
  repoint the running deployments directly (quick, but see the warning below):

  ```bash
  # Find the exact tags that were loaded into the kind node:
  docker exec kagenti-control-plane crictl images | grep -E "kagenti-ui-v2|kagenti-backend"

  # Repoint the running deployments at those tags (container names: backend / frontend):
  kubectl set image deploy/kagenti-backend backend=ghcr.io/kagenti/kagenti-backend:<TAG> -n kagenti-system
  kubectl set image deploy/kagenti-ui      frontend=ghcr.io/kagenti/kagenti-ui-v2:<TAG>   -n kagenti-system
  kubectl rollout status deploy/kagenti-backend -n kagenti-system
  ```

  > **Warning:** `kubectl set image` is a live override that Helm does not know
  > about. The next `helm upgrade` reverts the deployment to the chart's image
  > tag. For a durable setup, build images that match the chart's image values
  > (the `kind-full-test.sh` install path does this), rather than hand-patching.

## B. Enable on a fresh cluster

Add to your dev values file (e.g. `deployments/envs/dev_values.yaml`) under
`featureFlags:`:

```yaml
featureFlags:
  traceAnalysis: true
```

Then run the normal installer:

```bash
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy
```

## C. Local backend only (no cluster)

```bash
cd kagenti/backend && source .venv/bin/activate
export KAGENTI_FEATURE_FLAG_TRACE_ANALYSIS=true
export TRACE_ANALYSIS_DASHBOARD_URL="http://trace-analysis.localtest.me:8080"
uvicorn app.main:app --reload --port 8000
```

## D. The backing service

The flag both renders the Observability card **and** deploys the backing
`trace-analysis` component into `kagenti-system` at
`trace-analysis.<domainName>:8080`. No separate install step is needed.

Override the defaults under `traceAnalysis:` in your values (see
`charts/kagenti/values.yaml`):

```yaml
traceAnalysis:
  image:
    tag: latest                    # pin to a release tag instead of latest
  mlflowTrackingUri: "http://mlflow:5000"
  maxTraces: 50
  mlflowAuth:
    enabled: false                 # set true when MLflow has mlflow-oidc-auth on;
    secretName: mlflow-oauth-secret # pulls OAuth2 client-credentials from this secret
```

The component reads traces from MLflow, so MLflow must be reachable at
`traceAnalysis.mlflowTrackingUri` for the card's data to populate.

## Verifying end to end

| Layer | Check | Expected |
|-------|-------|----------|
| Helm | `helm get values kagenti -n kagenti-system` | `featureFlags.traceAnalysis: true` |
| Pod env | `kubectl get deploy kagenti-backend -n kagenti-system -o yaml \| grep TRACE_ANALYSIS` | env vars present |
| API | `GET /api/v1/config/features` | `"traceAnalysis": true` present in JSON |
| API | `GET /api/v1/config/dashboards` | `"traceAnalysis": "<url>"` |
| UI | Observability page | Trace Analysis card visible |

## Reapply

```bash
helm template kagenti charts/kagenti \
  -f deployments/envs/dev_values.yaml \
  --set openshift=false \
  -s templates/trace-analysis.yaml \
  | kubectl apply -f -
```
