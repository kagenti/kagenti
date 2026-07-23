---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Enabling the Trace Analysis Feature

The `trace_analysis` feature adds a **Trace Analysis** card to the Observability
page **and** deploys the backing `trace-analysis` component
(`ghcr.io/rossoctl/trace-analysis`) into `rossoctl-system`. When the flag is on,
the rossoctl chart renders the Deployment/Service/Route automatically — no
separate install is required.

Like all Rossoctl features, it is gated behind a feature flag that is **off by
default** (see the Feature Flags section of [CLAUDE.md](../CLAUDE.md)).

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

## A. Enable the on a kind installation

```bash

 # 1. Start the Rossoctl installation  
 kind delete cluster --name rossoctl ; \
  env CONTAINER_ENGINE=podman \
  scripts/kind/setup-rossoctl.sh --with-all --preload-images \
  --rossoctl-values deployments/envs/enable_trace_analysis.yaml ; \
  .github/scripts/local-setup/show-services.sh

# 2. While the installation is running (but after the cluster is created) ,  build and upload the image to the cluster

cd /path/to/rossoctl-trace-analysis
make TAG=latest build-load

cd /path/to/rossoctl
make TAG=latest build-load-ui           



