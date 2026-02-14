# Dockerfile for OTEL-enhanced ext_proc
# Builds the Go ext_proc with OpenTelemetry root span creation
FROM golang:1.23-alpine AS builder

WORKDIR /app

# Copy go module files first for caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY *.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -o /go-processor .

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /go-processor .

EXPOSE 9090

CMD ["./go-processor"]
