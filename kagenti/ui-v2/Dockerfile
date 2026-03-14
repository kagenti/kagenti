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
FROM nginx:1.29-alpine@sha256:1d13701a5f9f3fb01aaa88cef2344d65b6b5bf6b7d9fa4cf0dca557a8d7702ba

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

# Run nginx
CMD ["nginx", "-g", "daemon off;"]
