# Kagenti TUI

> **EXPERIMENTAL** — This is an early-stage terminal UI for Kagenti. APIs and features may change.

A terminal user interface for the Kagenti platform, built with [Bubble Tea](https://github.com/charmbracelet/bubbletea). Connects to the same FastAPI backend as the web UI.

## Install

```bash
# From repo root
make build-tui

# Or install to $GOPATH/bin
make install-tui

# Or from tui/ directly
cd kagenti/tui
make build      # → bin/kagenti-tui
make install    # → $GOPATH/bin/kagenti-tui
```

## Usage

```bash
kagenti-tui --url http://kagenti-ui.localtest.me:8080
```

### Flags

| Flag | Env Var | Default | Description |
|------|---------|---------|-------------|
| `--url` | `KAGENTI_URL` | `http://localhost:8080` | Backend URL |
| `--token` | `KAGENTI_TOKEN` | | Auth token |
| `--namespace` | `KAGENTI_NAMESPACE` | `team1` | Default namespace |
| `--version` | | | Print version |

### Config File

Settings persist in `~/.config/kagenti/tui.yaml`. Resolution order: defaults → config file → env vars → CLI flags.

## Commands

Type `/` to open the command prompt with autocomplete.

| Command | Description |
|---------|-------------|
| `/agents` | List agents in current namespace |
| `/agent <name>` | Show agent details |
| `/tools` | List tools in current namespace |
| `/tool <name>` | Show tool details |
| `/chat <agent>` | Chat with an agent (SSE streaming) |
| `/deploy agent` | Deploy agent (interactive form) |
| `/deploy tool` | Deploy tool (interactive form) |
| `/delete <type> <name>` | Delete agent or tool |
| `/ns <name>` | Switch namespace |
| `/login` | Authenticate with Keycloak (device code flow) |
| `/logout` | Clear auth token |
| `/status` | Return to home dashboard |
| `/help` | Show all commands |
| `/quit` | Exit |

## Keys

| Key | Action |
|-----|--------|
| `/` | Open command input |
| `Esc` | Return to home / cancel |
| `Ctrl+C` | Quit |
| `↑/↓` | Navigate lists / autocomplete |
| `Tab` | Complete command |
| `Enter` | Select / submit |

## Development

```bash
cd kagenti/tui
make run        # Run with go run
make lint       # go vet
make test       # go test
make build      # Build binary
```
