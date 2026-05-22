# Windows Development with WSL

Kagenti requires **WSL (Windows Subsystem for Linux)** for development on Windows. Native Windows development is not supported due to Linux-specific filesystem conventions (e.g., colons in skill folder names).

## Prerequisites

1. **WSL 2** installed with a Linux distribution (Ubuntu recommended)
2. **Git** installed inside WSL
3. **VS Code** or **Cursor** (optional, for IDE integration)

## Setup

### 1. Clone into the Linux filesystem

Always clone the repository into your WSL home directory — **never** onto a Windows drive (`/mnt/c/`, `/mnt/d/`, etc.):

```bash
# Open WSL terminal (e.g., Ubuntu)
cd ~
mkdir -p projects && cd projects
git clone https://github.com/kagenti/kagenti.git
cd kagenti
```

> **Why not `/mnt/c/`?** Windows drives mounted in WSL enforce Windows filename restrictions. Characters like `:` (used in Kagenti skill folder names) are forbidden on Windows filesystems. The WSL-native filesystem (`~/`) supports all Linux-valid characters.

### 2. IDE integration

#### VS Code

Install the [WSL Extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-wsl), then from your WSL terminal:

```bash
cd ~/projects/kagenti
code .
```

VS Code opens with full access to the Linux filesystem, terminal, and extensions.

#### Cursor

Cursor supports WSL via the same Remote - WSL extension. Open from the WSL terminal:

```bash
cd ~/projects/kagenti
cursor .
```

### 3. Claude Code

Run Claude Code from the WSL terminal inside the cloned repo:

```bash
cd ~/projects/kagenti
claude
```

All skill files (including those with `:` in folder names) will load correctly.

## Common issues

### `error: invalid path '.claude/skills/auth:keycloak-confidential-client/SKILL.md'`

This error means you cloned onto a Windows drive. Fix:

```bash
# Remove the broken clone
rm -rf /mnt/c/Users/YourName/kagenti

# Clone into the Linux filesystem instead
cd ~/projects
git clone https://github.com/kagenti/kagenti.git
```

### Slow file operations

If you experience slow `git` or build operations, verify you're on the Linux filesystem:

```bash
pwd
# Should show /home/yourname/... NOT /mnt/c/...
```

## Performance notes

The WSL-native Linux filesystem is significantly faster than accessing Windows drives through `/mnt/c/`. Always keep your working copy on the Linux side for best performance with:

- Git operations
- Node.js / npm / pnpm
- Python / uv
- Docker builds
