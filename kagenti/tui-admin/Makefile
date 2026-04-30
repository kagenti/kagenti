MODULE := github.com/kagenti/kagenti/kagenti/tui-admin
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS := -ldflags "-X $(MODULE)/internal/version.Version=$(VERSION)"
BIN := bin/kagenti-admin

.PHONY: build install run lint test clean tidy

build: tidy
	go build $(LDFLAGS) -o $(BIN) .

install: tidy
	go install $(LDFLAGS) .

run: tidy
	go run $(LDFLAGS) .

lint:
	go vet ./...

test:
	go test ./... -v -race -count=1

clean:
	rm -rf bin/

tidy:
	go mod tidy
