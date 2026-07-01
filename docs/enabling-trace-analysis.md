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
| Override values | `deployments/envs/enable_trace_analysis.yaml` (enables flag + pins images to `:latest`) |

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


# 1. Build and load the trace-analysis image into Kind
#    (from the kagenti-trace-analysis repo)
cd /path/to/kagenti-trace-analysis
make build-load

# 2. Build and load the kagenti UI + backend images into Kind
#    Needs docker buildx / BuildKit (see "Build prerequisite" above).
cd /path/to/kagenti
make build-load-ui                       # or -frontend / -backend for one side only


## B. To redploy only changes
