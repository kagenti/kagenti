# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

# Stage 1: Build the React application
FROM node:25-alpine@sha256:5209bcaca9836eb3448b650396213dbe9d9a34d31840c2ae1f206cb2986a8543 AS builder

WORKDIR /app

# Copy package files
COPY ui-v2/package.json ./
# Note: If using npm, use package-lock.json instead
# COPY package-lock.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY ui-v2/ .

# Build the application
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.29-alpine@sha256:f46cb72c7df02710e693e863a983ac42f6a9579058a59a35f1ae36c9958e4ce0

# Copy nginx configuration template
COPY ui-v2/nginx.conf /etc/nginx/templates/default.conf.template

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Cap worker processes to avoid OOM on high-core nodes
RUN sed -i 's/worker_processes\s*auto/worker_processes 4/' /etc/nginx/nginx.conf

# Make directories writable for arbitrary UIDs (OpenShift restricted SCC)
RUN chmod -R g+rwx /var/cache/nginx /var/log/nginx /usr/share/nginx/html /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chmod g+rw /var/run/nginx.pid

USER 1001

# OpenShift DNS ClusterIP default; override at deploy time for other platforms
ENV DNS_RESOLVER="172.30.0.10"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

CMD ["/bin/sh", "-c", "envsubst '${DNS_RESOLVER}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
