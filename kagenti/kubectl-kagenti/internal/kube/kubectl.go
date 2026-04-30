// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package kube

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

// LookPath returns kubectl or oc binary path.
func LookPath(custom string) (string, error) {
	if strings.TrimSpace(custom) != "" {
		return custom, nil
	}
	for _, name := range []string{"kubectl", "oc"} {
		if p, err := exec.LookPath(name); err == nil {
			return p, nil
		}
	}
	return "", exec.ErrNotFound
}

// GetConfigMapData returns a key from a ConfigMap's .data (empty if missing).
func GetConfigMapData(ctx context.Context, bin, ns, name, key string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := run(ctx, bin, "get", "configmap", name, "-n", ns, "-o", "jsonpath={.data."+key+"}")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

// GetSecretData returns decoded secret data for key (empty if key missing).
func GetSecretData(ctx context.Context, bin, ns, name, key string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := run(ctx, bin, "get", "secret", name, "-n", ns, "-o", "jsonpath={.data."+key+"}")
	if err != nil {
		return "", err
	}
	s := strings.TrimSpace(string(out))
	if s == "" {
		return "", fmt.Errorf("secret %s/%s: key %s empty or not found", ns, name, key)
	}
	b, err := base64.StdEncoding.DecodeString(s)
	if err != nil {
		return "", fmt.Errorf("decode secret key %s: %w", key, err)
	}
	return string(b), nil
}

// GetSecretDataOptional decodes a secret key when present; empty string if absent.
func GetSecretDataOptional(ctx context.Context, bin, ns, name, key string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	out, err := run(ctx, bin, "get", "secret", name, "-n", ns, "-o", "jsonpath={.data."+key+"}")
	if err != nil {
		return "", err
	}
	s := strings.TrimSpace(string(out))
	if s == "" {
		return "", nil
	}
	b, err := base64.StdEncoding.DecodeString(s)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func run(ctx context.Context, bin string, args ...string) ([]byte, error) {
	var stderr bytes.Buffer
	cmd := exec.CommandContext(ctx, bin, args...)
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("%s %v: %w: %s", bin, args, err, strings.TrimSpace(stderr.String()))
	}
	return out, nil
}

// CurrentNamespace returns the namespace from the current kube context (kubectl/oc).
// If unset in kubeconfig, returns "default".
func CurrentNamespace(ctx context.Context) (string, error) {
	bin, err := LookPath(strings.TrimSpace(os.Getenv("KAGENTI_KUBECTL")))
	if err != nil {
		return "default", nil
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	out, err := run(ctx, bin, "config", "view", "--minify", "-o", "jsonpath={..namespace}")
	if err != nil {
		return "default", nil
	}
	ns := strings.TrimSpace(string(out))
	if ns == "" {
		return "default", nil
	}
	return ns, nil
}
