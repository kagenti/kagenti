package main

import (
	"fmt"
	"os"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cli"
)

func main() {
	if err := cli.NewRootCmd().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
