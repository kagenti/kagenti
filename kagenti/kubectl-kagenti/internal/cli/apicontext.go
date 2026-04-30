// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/config"
	"github.com/spf13/cobra"
)

func loadAPI(cmd *cobra.Command) (baseURL, token string, err error) {
	cfg, err := config.Load()
	if err != nil {
		return "", "", err
	}
	baseURL, err = cfg.ResolveBackendURL(cmd.Context(), rootBackendDiscovery)
	if err != nil {
		return "", "", err
	}
	token, err = cfg.BearerToken()
	if err != nil {
		return "", "", err
	}
	if token == "" {
		return "", "", fmt.Errorf("not authenticated: run kubectl kagenti auth login (or set %s)", config.EnvTokenName())
	}
	return baseURL, token, nil
}
