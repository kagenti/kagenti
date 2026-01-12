# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

# Stage 1: Build the React application
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json ./
# Note: If using npm, use package-lock.json instead
# COPY package-lock.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.25-alpine

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

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
