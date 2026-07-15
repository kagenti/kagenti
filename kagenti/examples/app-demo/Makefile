CLUSTER_NAME ?= kagenti
NAMESPACE ?= kagenti-system
IMAGE_PREFIX ?= localhost/

.PHONY: dev-backend dev-frontend build build-backend build-frontend build-keycloak \
        kind-load deploy keycloak-setup grant-agent-access clean all

# --- Full workflow: build, load, setup keycloak, deploy ---

# Set `DOCKER_BUILD_FLAGS=--load` if using Podman

all: build kind-load keycloak-setup deploy
	@echo ""
	@echo "=========================================="
	@echo " App Demo deployed successfully!"
	@echo "=========================================="
	@echo ""
	@echo "🌐 Access the app at:"
	@echo "   http://app-demo.localtest.me:8080"
	@echo ""
	@TOKEN_BROKER_URL=$$(kubectl get configmap app-demo-config -n $(NAMESPACE) -o jsonpath='{.data.TOKEN_BROKER_URL}' 2>/dev/null || echo ""); \
	if [ -n "$$TOKEN_BROKER_URL" ]; then \
		echo "🔐 Token Broker: ENABLED ($$TOKEN_BROKER_URL)"; \
	else \
		echo "🔐 Token Broker: DISABLED"; \
	fi
	@echo ""
	@echo "Next step: grant user access to agents."
	@echo ""
	@echo "  Option A (automated - configures demo agents):"
	@echo "    make grant-agent-access"
	@echo ""
	@echo "  Option B (manual - for any agent):"
	@echo "    See docs/agent-access-setup.md"
	@echo ""
	@echo "After granting access, users must log out and back in."
	@echo ""

# --- Local development ---

dev-backend:
	cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	cd frontend && npm run dev

# --- Docker builds ---

build-backend:
	docker build -t $(IMAGE_PREFIX)app-demo-backend:latest -f backend/Dockerfile backend/ $(DOCKER_BUILD_FLAGS)

build-frontend:
	docker build -t $(IMAGE_PREFIX)app-demo-frontend:latest -f frontend/Dockerfile frontend/ $(DOCKER_BUILD_FLAGS)

build-keycloak:
	docker build -t $(IMAGE_PREFIX)app-demo-keycloak:latest -f keycloak/Dockerfile keycloak/ $(DOCKER_BUILD_FLAGS)

build: build-backend build-frontend build-keycloak

# --- Kind cluster ---

kind-load: build
	kind load docker-image $(IMAGE_PREFIX)app-demo-backend:latest --name $(CLUSTER_NAME)
	kind load docker-image $(IMAGE_PREFIX)app-demo-frontend:latest --name $(CLUSTER_NAME)
	kind load docker-image $(IMAGE_PREFIX)app-demo-keycloak:latest --name $(CLUSTER_NAME)
	# Pre-load the image (which helps with image pull rate limiting in some environments)
	# Ignores failures; pull with `docker pull curlimages/curl:8.13.0` for this behavior.
	kind load docker-image curlimages/curl:8.13.0 --name $(CLUSTER_NAME)  2>/dev/null || true

keycloak-setup: kind-load
	kubectl delete job app-demo-keycloak-client -n $(NAMESPACE) --ignore-not-found
	kubectl apply -f k8s/keycloak-client-job.yaml
	@echo "Waiting for Keycloak client registration job..."
	kubectl wait --for=condition=complete --timeout=120s job/app-demo-keycloak-client -n $(NAMESPACE)

# --- Agent access (optional, run after agents are deployed) ---

grant-agent-access: kind-load
	kubectl delete job app-demo-agent-access -n $(NAMESPACE) --ignore-not-found
	kubectl apply -f k8s/agent-access-job.yaml
	@echo "Waiting for agent access configuration job..."
	kubectl wait --for=condition=complete --timeout=120s job/app-demo-agent-access -n $(NAMESPACE)
	@echo ""
	@echo "Agent access configured. Users must log out and back in."
	@echo ""
	@echo "🌐 Access the app at:"
	@echo "   http://app-demo.localtest.me:8080"
	@echo ""

deploy: kind-load keycloak-setup
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/backend-deployment.yaml
	kubectl apply -f k8s/frontend-deployment.yaml
	kubectl apply -f k8s/httproute.yaml
	@echo "Restarting deployments to pick up new images..."
	kubectl rollout restart deployment/app-demo-backend -n $(NAMESPACE)
	kubectl rollout restart deployment/app-demo-frontend -n $(NAMESPACE)
	@echo "Waiting for rollout to complete..."
	kubectl rollout status deployment/app-demo-backend -n $(NAMESPACE) --timeout=120s
	kubectl rollout status deployment/app-demo-frontend -n $(NAMESPACE) --timeout=120s

clean:
	kubectl delete -f k8s/ --ignore-not-found
