# Copyright 2025 IBM Corp.
# SPDX-License-Identifier: Apache-2.0

BINARY     ?= kubectl-kagenti
VERSION    ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
GIT_COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo none)
LDFLAGS    = -s -w -X github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/cli.Version=$(VERSION) -X github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/cli.GitCommit=$(GIT_COMMIT)

.PHONY: build test install clean krew-pack

build:
	go build -trimpath -ldflags "$(LDFLAGS)" -o $(BINARY) ./cmd/kubectl-kagenti

test:
	go test ./...

install: build
	install -d "$(HOME)/.local/bin"
	install -m 0755 $(BINARY) "$(HOME)/.local/bin/$(BINARY)"
	@echo 'Ensure ~/.local/bin is on PATH, then: kubectl kagenti --help'

# Build release archives (same layout as goreleaser) for local Krew testing.
krew-pack: build
	@mkdir -p dist
	@OS=$$(go env GOOS); ARCH=$$(go env GOARCH); \
	T=dist/$(BINARY)_$(VERSION)_$${OS}_$${ARCH}.tar.gz; \
	tar -czf "$$T" -C $$(dirname $(BINARY)) $$(basename $(BINARY)); \
	SHASUM=$$(shasum -a 256 "$$T" | awk '{print $$1}'); \
	echo "$$T sha256=$$SHASUM"; \
	echo "Update deploy/krew/kagenti.yaml uri (file://$$PWD/$$T) and sha256 for: kubectl krew install --manifest=..."

clean:
	rm -f $(BINARY)
	rm -rf dist/
