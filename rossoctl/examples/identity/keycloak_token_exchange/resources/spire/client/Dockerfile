FROM ghcr.io/spiffe/spiffe-helper:0.8.0@sha256:4d9863034d8f95d5b6592095b57a38828e54b4e92f66d744a6ed353f6fc0bf7f as spiffe-helper

# Pin Alpine version for reproducible builds
FROM alpine:3.21@sha256:c3f8e73fdb79deaebaa2037150150191b9dcbfba68b4a46d70103204c53f4709 as alpine

WORKDIR /app

RUN apk --no-cache add curl

COPY --from=spiffe-helper /spiffe-helper /spiffe-helper
COPY helper.conf /app/helper.conf

ENTRYPOINT ["/spiffe-helper"]

CMD []
