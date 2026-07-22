# Multi-stage build for the rossoctl Go CLI (zero third-party deps).
#
#   docker build -t quay.io/aslomnet/rossoctl \
#     --build-arg VERSION="$(git describe --tags --always)" \
#     --build-arg COMMIT="$(git rev-parse --short HEAD)" .
#   docker run --rm quay.io/aslomnet/rossoctl version
#   docker run --rm quay.io/aslomnet/rossoctl doctor
FROM golang:1.23-alpine AS build
WORKDIR /src
# No third-party dependencies, so there is nothing to `go mod download`.
COPY go.mod ./
COPY *.go ./
ARG VERSION=dev
ARG COMMIT=none
RUN CGO_ENABLED=0 go build -trimpath \
    -ldflags "-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" \
    -o /out/rossoctl .

# Distroless static, non-root: tiny, no shell, no package manager.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/rossoctl /rossoctl
ENTRYPOINT ["/rossoctl"]
CMD ["--version"]
