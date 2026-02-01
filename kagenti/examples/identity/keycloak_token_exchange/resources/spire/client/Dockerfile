FROM ghcr.io/spiffe/spiffe-helper:0.8.0 as spiffe-helper

# Pin Alpine version for reproducible builds
FROM alpine:3.21 as alpine

WORKDIR /app

RUN apk --no-cache add curl

COPY --from=spiffe-helper /spiffe-helper /spiffe-helper
COPY helper.conf /app/helper.conf

ENTRYPOINT ["/spiffe-helper"]

CMD []
