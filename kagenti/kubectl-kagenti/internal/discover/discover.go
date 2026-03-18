// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

// Package discover resolves the Kagenti API base URL from the cluster when not configured explicitly.
package discover

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

const (
	DefaultNamespace = "kagenti-system"
	RouteName        = "kagenti-api"
	ServiceName      = "kagenti-backend"
)

// Mode controls how the backend URL is discovered.
type Mode int

const (
	// Auto tries OpenShift Route kagenti-api first, then in-cluster Service URL.
	Auto Mode = iota
	// RouteOnly requires Route kagenti-api (HTTPS host from the route).
	RouteOnly
	// ServiceOnly uses Service kagenti-backend cluster DNS (HTTP); use from inside the cluster or when you intentionally skip the route.
	ServiceOnly
)

// ParseMode maps config/env strings to Mode.
func ParseMode(s string) Mode {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "route":
		return RouteOnly
	case "service":
		return ServiceOnly
	default:
		return Auto
	}
}

// Options for cluster discovery.
type Options struct {
	Mode      Mode
	Namespace string
	// Kubectl overrides the kubectl/oc binary path (tests).
	Kubectl string
	Timeout time.Duration
}

func (o *Options) ns() string {
	if strings.TrimSpace(o.Namespace) != "" {
		return o.Namespace
	}
	return DefaultNamespace
}

func (o *Options) timeout() time.Duration {
	if o.Timeout > 0 {
		return o.Timeout
	}
	return 15 * time.Second
}

// Resolve returns the API base URL using the current kube context.
func Resolve(ctx context.Context, o Options) (string, error) {
	bin, err := o.kubectlPath()
	if err != nil {
		return "", fmt.Errorf("need kubectl or oc on PATH to discover backend URL: %w", err)
	}
	ctx, cancel := context.WithTimeout(ctx, o.timeout())
	defer cancel()

	switch o.Mode {
	case ServiceOnly:
		return serviceBaseURL(ctx, bin, o.ns())
	case RouteOnly:
		u, err := routeBaseURL(ctx, bin, o.ns())
		if u != "" {
			return u, nil
		}
		return "", fmt.Errorf("route %s/%s required (mode=route): %w", o.ns(), RouteName, err)
	default: // Auto
		u, rerr := routeBaseURL(ctx, bin, o.ns())
		if u != "" {
			return u, nil
		}
		su, serr := serviceBaseURL(ctx, bin, o.ns())
		if serr != nil {
			if rerr != nil && !errors.Is(rerr, errRouteUnavailable) {
				return "", fmt.Errorf("route %s/%s unavailable (%v); service %s/%s: %w",
					o.ns(), RouteName, rerr, o.ns(), ServiceName, serr)
			}
			return "", fmt.Errorf("service %s/%s (fallback after route): %w", o.ns(), ServiceName, serr)
		}
		return su, nil
	}
}

func (o *Options) kubectlPath() (string, error) {
	if strings.TrimSpace(o.Kubectl) != "" {
		return o.Kubectl, nil
	}
	for _, name := range []string{"kubectl", "oc"} {
		if p, err := exec.LookPath(name); err == nil {
			return p, nil
		}
	}
	return "", exec.ErrNotFound
}

var errRouteUnavailable = errors.New("route not available")

func routeBaseURL(ctx context.Context, bin, ns string) (string, error) {
	var lastErr error
	for _, jp := range []string{
		`{.status.ingress[0].host}`,
		`{.spec.host}`,
	} {
		out, err := kubectlJSONPath(ctx, bin, "get", "route", RouteName, "-n", ns, "-o", "jsonpath="+jp)
		if err != nil {
			lastErr = err
			if isRouteCRDMissing(err) || isNotFound(err) {
				return "", errRouteUnavailable
			}
			continue
		}
		host := strings.TrimSpace(string(out))
		if host != "" {
			if strings.HasPrefix(host, "http://") || strings.HasPrefix(host, "https://") {
				return strings.TrimRight(host, "/"), nil
			}
			return "https://" + strings.TrimRight(host, "/"), nil
		}
	}
	if lastErr != nil && !errors.Is(lastErr, errRouteUnavailable) {
		return "", lastErr
	}
	return "", errRouteUnavailable
}

func isRouteCRDMissing(err error) bool {
	s := strings.ToLower(err.Error())
	return strings.Contains(s, `resource type "route"`) ||
		strings.Contains(s, "couldn't find resource") && strings.Contains(s, "route")
}

func isNotFound(err error) bool {
	s := err.Error()
	return strings.Contains(s, "NotFound") || strings.Contains(s, "not found")
}

func serviceBaseURL(ctx context.Context, bin, ns string) (string, error) {
	out, err := kubectlJSONPath(ctx, bin, "get", "svc", ServiceName, "-n", ns,
		"-o", `jsonpath={.spec.ports[?(@.name=="http")].port}`)
	if err != nil {
		if isNotFound(err) {
			return "", fmt.Errorf("service %s/%s not found: %w", ns, ServiceName, err)
		}
		return "", err
	}
	port := strings.TrimSpace(string(out))
	if port == "" {
		out, err = kubectlJSONPath(ctx, bin, "get", "svc", ServiceName, "-n", ns, "-o", "jsonpath={.spec.ports[0].port}")
		if err != nil {
			return "", err
		}
		port = strings.TrimSpace(string(out))
	}
	if port == "" {
		return "", fmt.Errorf("could not read port for service %s/%s", ns, ServiceName)
	}
	if _, err := strconv.Atoi(port); err != nil {
		return "", fmt.Errorf("invalid port %q for service %s/%s", port, ns, ServiceName)
	}
	host := fmt.Sprintf("%s.%s.svc.cluster.local", ServiceName, ns)
	return fmt.Sprintf("http://%s:%s", host, port), nil
}

func kubectlJSONPath(ctx context.Context, bin string, args ...string) ([]byte, error) {
	var stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, bin, args...)
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("%s %v: %w: %s", bin, args, err, strings.TrimSpace(stderr.String()))
	}
	return out, nil
}
