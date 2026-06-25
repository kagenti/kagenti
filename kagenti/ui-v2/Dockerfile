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
FROM nginx:1.31-alpine@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa

# Copy nginx configuration (server block only; mounted at conf.d/default.conf).
COPY ui-v2/nginx.conf /etc/nginx/conf.d/default.conf

# Pin worker_processes to a fixed count in the *main* nginx.conf.
# The stock image ships `worker_processes auto;`, which spawns one worker per
# *host* CPU and ignores the container's cgroup CPU limit. On large nodes (e.g.
# OpenShift) that forked ~one worker per core and OOMKilled the pod (kagenti#1991).
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
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

# Run nginx (worker_processes is pinned in the main conf above, not via -g).
CMD ["nginx", "-g", "daemon off;"]
