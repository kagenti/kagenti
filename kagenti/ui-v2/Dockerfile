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
FROM nginx:1.31-alpine@sha256:8b1e78743a03dbb2c95171cc58639fef29abc8816598e27fb910ed2e621e589a

# Copy nginx configuration
COPY ui-v2/nginx.conf /etc/nginx/conf.d/default.conf

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

# Run nginx.
# Pin worker_processes via -g rather than relying on the base image's default
# `worker_processes auto;`. `auto` spawns one worker per *host* CPU and ignores
# the container's cgroup CPU limit, so on large nodes (e.g. OpenShift) nginx
# forked ~one worker per core, blowing past the memory limit and OOMKilling the
# pod. The container is capped at a fraction of a CPU, so a single worker is
# ample and keeps the memory footprint independent of node size. See kagenti#1991.
# (worker_processes is a main-context directive, so it cannot live in the
# server-block-only nginx.conf mounted at conf.d/default.conf.)
CMD ["nginx", "-g", "daemon off; worker_processes 1;"]
