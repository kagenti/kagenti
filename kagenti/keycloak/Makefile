SPI_VERSION      := 0.1.0
# Kagenti uses 26.5.2.  26.6.0 is newer but has more security advisories.
KEYCLOAK_VERSION := 26.5.2

JAR := target/github-org-authenticator-$(SPI_VERSION).jar

REGISTRY  ?= ghcr.io/kagenti/kagenti
IMAGE     ?= github-org-keycloak
IMAGE_TAG ?= $(SPI_VERSION)-kc$(KEYCLOAK_VERSION)
IMAGE_REF := $(REGISTRY)/$(IMAGE):$(IMAGE_TAG)

# Auto-detect if the 'docker' client is using a Podman backend.
# We check 'docker info' for Podman's default storage path.
IS_PODMAN_DETECT := $(shell docker info 2>/dev/null | grep -q "/var/lib/containers/storage" && echo "true")

# Allow user override, e.g., 'make DOCKER_IS_PODMAN=true' or '...=false'
# If DOCKER_IS_PODMAN is not set by the user, use the auto-detected value.
ifeq ($(DOCKER_IS_PODMAN),)
  DOCKER_IS_PODMAN := $(IS_PODMAN_DETECT)
endif

PLATFORMS ?= linux/amd64,linux/arm64

# Host platform — used to load just one arch into the local image store
# during `make image`, since multi-platform manifests can't be --load'd.
HOST_ARCH := $(shell uname -m)
ifeq ($(HOST_ARCH),x86_64)
  HOST_PLATFORM := linux/amd64
else ifeq ($(HOST_ARCH),aarch64)
  HOST_PLATFORM := linux/arm64
else ifeq ($(HOST_ARCH),arm64)
  HOST_PLATFORM := linux/arm64
else
  HOST_PLATFORM := linux/amd64
endif

.PHONY: all package clean image push install-info

all: package

package: $(JAR)

$(JAR):
	mvn package

clean:
	mvn clean

image:
	@if [ "$(DOCKER_IS_PODMAN)" = "true" ]; then \
		echo "Info: Podman backend detected."; \
	fi
	docker buildx build \
	    --platform $(PLATFORMS) \
	    --build-arg KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:$(KEYCLOAK_VERSION) \
	    -t $(IMAGE_REF) .
	docker buildx build \
	    --platform $(HOST_PLATFORM) \
	    --build-arg KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:$(KEYCLOAK_VERSION) \
	    -t $(IMAGE_REF) --load .
	@echo "Built $(IMAGE_REF) for $(PLATFORMS) (loaded $(HOST_PLATFORM) locally)"

push:
	docker buildx build \
	    --platform $(PLATFORMS) \
	    --build-arg KEYCLOAK_IMAGE=quay.io/keycloak/keycloak:$(KEYCLOAK_VERSION) \
	    -t $(IMAGE_REF) --push .
	@echo "Pushed $(IMAGE_REF) for $(PLATFORMS)"

install-info:
	@echo "JAR-only install:"
	@echo "  Copy $(JAR) into your Keycloak/RHBK providers directory, then run:"
	@echo "    kc.sh build"
	@echo "  and restart Keycloak."
	@echo
	@echo "Custom image install:"
	@echo "  make push                                # builds and pushes $(IMAGE_REF)"
	@echo "  Override image in your Helm values / Operator CR to: $(IMAGE_REF)"
