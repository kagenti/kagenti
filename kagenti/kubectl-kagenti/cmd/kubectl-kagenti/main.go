// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"os"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/cli"
)

func main() {
	if err := cli.Execute(); err != nil {
		os.Exit(1)
	}
}
