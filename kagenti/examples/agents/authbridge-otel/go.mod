module github.com/kagenti/authbridge-otel-processor

go 1.23.0

require (
	github.com/envoyproxy/go-control-plane/envoy v1.35.0
	github.com/lestrrat-go/jwx/v2 v2.1.6
	go.opentelemetry.io/otel v1.36.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.36.0
	go.opentelemetry.io/otel/sdk v1.36.0
	google.golang.org/grpc v1.75.1
)
