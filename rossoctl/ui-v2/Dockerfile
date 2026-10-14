# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

# Stage 1: Build the React application
FROM node:26-slim@sha256:aa27a5fbf5acb298116a38133794f080406c6f8dfe52e2e2836bb55dc7cae8f0 AS builder

WORKDIR /app

# Copy package files
COPY ui-v2/package.json ui-v2/package-lock.json ./

# Install dependencies (locked via package-lock.json)
# Rollup needs the explicit glibc binary in slim/Debian (not auto-resolved like in alpine)
# hadolint ignore=DL3016
RUN npm ci --legacy-peer-deps && \
    npm install @rollup/rollup-linux-x64-gnu --save-optional

# Copy source code
COPY ui-v2/ .

ARG RELEASE_TAG=unknown
RUN sed -i -r 's/^\ \ "version": (.*)/  "version": "'${RELEASE_TAG}'",/' package.json

# Build the application
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.31-alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2

# Copy nginx configuration (server block only; mounted at conf.d/default.conf).
# Force world-readable perms: the container runs as non-root UID 1001 (see below),
# and COPY preserves the builder's umask — under podman that yields root-only 0640,
# so nginx (UID 1001) hits "[emerg] Permission denied" reading default.conf and
# crashloops. BuildKit/docker happens to copy 0644; the explicit chmod makes the
# image builder-independent.
COPY ui-v2/nginx.conf /etc/nginx/conf.d/default.conf
RUN chmod 0644 /etc/nginx/conf.d/default.conf

# Pin worker_processes to a fixed count in the *main* nginx.conf.
# The stock image ships `worker_processes auto;`, which spawns one worker per
# *host* CPU and ignores the container's cgroup CPU limit. On large nodes (e.g.
# OpenShift) that forked ~one worker per core and OOMKilled the pod (rossoctl#1991).
# Done here at build time (as root) rather than via `nginx -g`: passing
# worker_processes through -g collides with the directive already in the main
# conf ("[emerg] worker_processes directive is duplicate"), and the runtime
# NGINX_ENTRYPOINT_WORKER_PROCESSES_AUTOTUNE cannot rewrite the root-owned main
# conf under the non-root USER below. A fixed count keeps the memory footprint
# independent of node size; the container is capped at a fraction of a CPU.
RUN sed -i 's/^worker_processes.*/worker_processes 1;/' /etc/nginx/nginx.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Add non-root user for security
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /usr/share/nginx/html && \
    chown -R appuser:appgroup /var/cache/nginx && \
    chown -R appuser:appgroup /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R appuser:appgroup /var/run/nginx.pid

USER 1001

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/"]

# Run nginx (worker_processes is pinned in the main conf above, not via -g).
CMD ["nginx", "-g", "daemon off;"]
