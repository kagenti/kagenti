// Command rossoctl is a Go stub of the Python `rossoctlx` CLI. The command
// surface mirrors rossoctlx (version, status, doctor, start, stop, log, agents,
// agent, completions); the stub commands do nothing yet. It ships a real
// self-update subcommand and a throttled "update available" notice.
//
// Install:  go install github.com/aslom/kagenti/scripts/rossoctl@rossoctlx
// Run:      go run github.com/aslom/kagenti/scripts/rossoctl@rossoctlx version
// Docker:   docker run --rm quay.io/aslomnet/rossoctl version
package main

import (
	"fmt"
	"os"
)

// Set at build time via -ldflags "-X main.version=... -X main.commit=...".
var (
	version = "dev"
	commit  = "none"
)

const usage = `rossoctl — Go stub of the rossoctlx CLI
(commands mirror rossoctlx; the stub commands currently do nothing)

Usage:
  rossoctl <command> [args]

Commands:
  version        Show client version
  status         (stub) Check if rossocortex is running
  doctor         (stub) Environment preflight            [alias: preflight]
  start          (stub) Start rossocortex
  stop           (stub) Stop rossocortex
  log            (stub) Show request log                 [alias: logs]
  agents         (stub) List registered agents
  agent          (stub) Create/retrieve agent credentials
  completions    (stub) Shell completion setup
  cortex         (stub) Manage rossocortex: 'cortex start|stop' == 'start|stop'
  self-update    Update rossoctl to the latest release   [--check|--dry-run|--version vX.Y.Z]
  help           Show this help

Flags:
  --version      Print client version and exit

Env:
  ROSSOCTL_NO_UPDATE_CHECK=1   Disable the passive "update available" notice
  ROSSOCTL_UPDATE_SLUG=o/r     Override the release repo (default aslom/kagenti)
  ROSSOCTL_UPDATE_BASE=url     Override the release host (default https://github.com)
`

func printVersion() {
	fmt.Printf("rossoctl %s (commit %s)\n", version, commit)
}

func stub(name string) {
	fmt.Printf("[stub] rossoctl %s: not implemented — Go stub mirroring rossoctlx\n", name)
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fmt.Print(usage)
		os.Exit(1)
	}

	switch args[0] {
	case "--version":
		printVersion()
		return
	case "-h", "--help", "help":
		fmt.Print(usage)
		return
	}

	cmd := args[0]
	rest := args[1:]

	// self-update runs before (and instead of) the passive nag.
	if cmd == "self-update" || cmd == "selfupdate" {
		if err := cmdSelfUpdate(rest); err != nil {
			fmt.Fprintln(os.Stderr, "self-update:", err)
			os.Exit(1)
		}
		return
	}

	// Throttled, best-effort "update available" notice (stderr, once/24h).
	maybeNotifyUpdate()

	switch cmd {
	case "version":
		printVersion()
	case "status", "doctor", "preflight", "start", "stop",
		"log", "logs", "agents", "agent", "completions":
		stub(cmd)
	case "cortex":
		// `cortex start|stop` mirror the top-level start|stop.
		if len(rest) >= 1 && (rest[0] == "start" || rest[0] == "stop") {
			stub("cortex " + rest[0])
		} else {
			fmt.Fprintln(os.Stderr, "usage: rossoctl cortex {start|stop}")
			os.Exit(1)
		}
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n\n", cmd)
		fmt.Fprint(os.Stderr, usage)
		os.Exit(1)
	}
}
