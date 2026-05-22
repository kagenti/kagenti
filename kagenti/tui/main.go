package main

import (
	"fmt"
	"os"

	"github.com/kagenti/kagenti/kagenti/tui/internal/cli"
)

func main() {
	if err := cli.NewRootCmd().Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
