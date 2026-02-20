.PHONY: lint
lint:
	cd kagenti/backend && uv sync --extra dev && uv run pylint app/

# Define variables
KIND_CLUSTER_NAME := kagenti
# Generate unique tag using git commit hash (short) or timestamp if not in git repo
TAG := $(shell git rev-parse --short HEAD 2>/dev/null | xargs -I {} sh -c 'echo "{}-$$(date +%s)"' || date +%s)

# Agent OAuth Secret
AGENT_OAUTH_SECRET_IMAGE := agent-oauth-secret
AGENT_OAUTH_SECRET_DIR := kagenti/auth/agent-oauth-secret
AGENT_OAUTH_SECRET_TAG := $(TAG)

# UI v2 Frontend
UI_FRONTEND_REPO := ghcr.io/kagenti/kagenti-ui-v2
UI_FRONTEND_TAG := $(TAG)
UI_FRONTEND_DIR := kagenti/ui-v2

# UI v2 Backend
UI_BACKEND_REPO := ghcr.io/kagenti/kagenti-backend
UI_BACKEND_TAG := $(TAG)
UI_BACKEND_DIR := kagenti/backend

# Shared Docker build context (matches CI build.yaml)
DOCKER_BUILD_CONTEXT := kagenti

# --- Conditional Build Flags Logic ---

# Auto-detect if the 'docker' client is using a Podman backend
# We check 'docker info' for Podman's default storage path.
IS_PODMAN_DETECT := $(shell docker info 2>/dev/null | grep -q "/var/lib/containers/storage" && echo "true")

# Allow user override, e.g., 'make DOCKER_IS_PODMAN=true' or '...=false'
# If DOCKER_IS_PODMAN is not set by the user, use the auto-detected value.
ifeq ($(DOCKER_IS_PODMAN),)
  DOCKER_IS_PODMAN := $(IS_PODMAN_DETECT)
endif

# Set the --load flag only if we are using a Podman backend
DOCKER_BUILD_FLAGS :=
ifeq ($(DOCKER_IS_PODMAN),true)
  DOCKER_BUILD_FLAGS := --load
endif

# --- End Logic ---

# Build and load agent-oauth-secret image into kind cluster for testing
.PHONY: build-load-agent-oauth-secret
build-load-agent-oauth-secret:
	@echo "Building $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG) image..."
	@if [ "$(DOCKER_IS_PODMAN)" = "true" ]; then \
		echo "Info: Podman backend detected. Using --load flag for build."; \
	fi
	# $(DOCKER_BUILD_FLAGS) will be '--load' for podman and empty for docker
	docker build -t $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG) -f $(AGENT_OAUTH_SECRET_DIR)/Dockerfile $(DOCKER_BUILD_CONTEXT) $(DOCKER_BUILD_FLAGS)
	@echo "Loading $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG) image into kind cluster $(KIND_CLUSTER_NAME)..."
	kind load docker-image $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG) --name $(KIND_CLUSTER_NAME)
	@echo "✓ $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG) image built and loaded successfully"
	@echo ""
	@echo "To use this image, update your deployment with:"
	@echo "  image: $(AGENT_OAUTH_SECRET_IMAGE):$(AGENT_OAUTH_SECRET_TAG)"

# Build UI v2 frontend image and load into kind cluster
.PHONY: build-load-ui-frontend
build-load-ui-frontend:
	@echo "=========================================="
	@echo "Building UI v2 Frontend"
	@echo "=========================================="
	@echo "Image: $(UI_FRONTEND_REPO):$(UI_FRONTEND_TAG)"
	@if [ "$(DOCKER_IS_PODMAN)" = "true" ]; then \
		echo "Info: Podman backend detected. Using --load flag for build."; \
	fi
	@echo ""
	docker build -t $(UI_FRONTEND_REPO):$(UI_FRONTEND_TAG) -f $(UI_FRONTEND_DIR)/Dockerfile $(DOCKER_BUILD_CONTEXT) $(DOCKER_BUILD_FLAGS)
	@echo ""
	@echo "Loading frontend image into kind cluster $(KIND_CLUSTER_NAME)..."
	kind load docker-image $(UI_FRONTEND_REPO):$(UI_FRONTEND_TAG) --name $(KIND_CLUSTER_NAME)
	@echo "✓ Frontend image loaded successfully"

# Build UI v2 backend image and load into kind cluster
.PHONY: build-load-ui-backend
build-load-ui-backend:
	@echo "=========================================="
	@echo "Building UI v2 Backend"
	@echo "=========================================="
	@echo "Image: $(UI_BACKEND_REPO):$(UI_BACKEND_TAG)"
	@if [ "$(DOCKER_IS_PODMAN)" = "true" ]; then \
		echo "Info: Podman backend detected. Using --load flag for build."; \
	fi
	@echo ""
	docker build -t $(UI_BACKEND_REPO):$(UI_BACKEND_TAG) -f $(UI_BACKEND_DIR)/Dockerfile $(DOCKER_BUILD_CONTEXT) $(DOCKER_BUILD_FLAGS)
	@echo ""
	@echo "Loading backend image into kind cluster $(KIND_CLUSTER_NAME)..."
	kind load docker-image $(UI_BACKEND_REPO):$(UI_BACKEND_TAG) --name $(KIND_CLUSTER_NAME)
	@echo "✓ Backend image loaded successfully"

# Build and load both UI v2 frontend and backend images
.PHONY: build-load-ui
build-load-ui: build-load-ui-frontend build-load-ui-backend
	@echo ""
	@echo "=========================================="
	@echo "✓ All UI v2 images built and loaded!"
	@echo "=========================================="
	@echo ""
	@echo "Frontend: $(UI_FRONTEND_REPO):$(UI_FRONTEND_TAG)"
	@echo "Backend:  $(UI_BACKEND_REPO):$(UI_BACKEND_TAG)"
	@echo ""
	@echo "To use these images with the Helm chart, run:"
	@echo ""
	@echo "  helm upgrade --install kagenti charts/kagenti \\"
	@echo "    --namespace kagenti-system \\"
	@echo "    --set openshift=false \\"
	@echo "    --set ui.frontend.image=$(UI_FRONTEND_REPO) \\"
	@echo "    --set ui.frontend.tag=$(UI_FRONTEND_TAG) \\"
	@echo "    --set ui.backend.image=$(UI_BACKEND_REPO) \\"
	@echo "    --set ui.backend.tag=$(UI_BACKEND_TAG) \\"
	@echo "    -f charts/kagenti/.secrets.yaml"
	@echo ""

# Help target for UI v2 builds
.PHONY: help-ui
help-ui:
	@echo "UI v2 Build Targets:"
	@echo "  make build-load-ui              - Build and load both frontend and backend"
	@echo "  make build-load-ui-frontend     - Build and load only frontend"
	@echo "  make build-load-ui-backend      - Build and load only backend"
	@echo ""
	@echo "Variables (can be overridden):"
	@echo "  KIND_CLUSTER_NAME=$(KIND_CLUSTER_NAME)"
	@echo "  UI_FRONTEND_REPO=$(UI_FRONTEND_REPO)"
	@echo "  UI_FRONTEND_TAG=$(UI_FRONTEND_TAG)"
	@echo "  UI_BACKEND_REPO=$(UI_BACKEND_REPO)"
	@echo "  UI_BACKEND_TAG=$(UI_BACKEND_TAG)"
	@echo ""
	@echo "Examples:"
	@echo "  make build-load-ui"
	@echo "  make build-load-ui UI_FRONTEND_TAG=v1.0.0 UI_BACKEND_TAG=v1.0.0"
	@echo "  make build-load-ui-frontend KIND_CLUSTER_NAME=my-cluster"
	@echo ""

	
# Define the path for the output file
PRELOAD_FILE := deployments/ansible/kind/preload-images.txt

# The primary task to list and filter images
.PHONY: preflight-check preload-file

# Verify required commands are available before running other targets
preflight-check:
	@# fail fast with a helpful message if any required command is missing
	@( for cmd in kubectl jq; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo >&2 "ERROR: '$$cmd' not found. Please install it (for example: 'brew install $$cmd' on macOS) and retry."; \
			exit 1; \
		fi; \
		done )

# The primary task to list and filter images; depend on the preflight check
preload-file: preflight-check
	@mkdir -p $$(dirname $(PRELOAD_FILE)) && \
	kubectl get pods --all-namespaces -o json | jq -r '.items[] | (.spec.containers // [])[].image, (.spec.initContainers // [])[].image' | sort -u | grep -E '^(docker\.io/|[^./]+/[^./])' | \
	tee $(PRELOAD_FILE) && \
	echo "Filtered local and docker.io images have been saved to $(PRELOAD_FILE)"