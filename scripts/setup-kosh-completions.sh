#!/bin/bash
# setup-kosh-completions.sh — Set up shell completions for kosh CLI
#
# Auto-detects zsh or bash and installs completions accordingly.
# Uses a symlink at ~/.local/bin/kosh.py so .zshrc/.bashrc never goes stale.
#
# Usage:
#   ./setup-kosh-completions.sh
#
# Run again after kosh.py changes to regenerate completions.
set -euo pipefail

KOSH_LINK="${HOME}/.local/bin/kosh.py"

# --- Detect shell ---

detect_shell() {
  local parent_shell
  parent_shell=$(ps -o comm= -p $PPID 2>/dev/null | sed 's|.*/||' | sed 's/^-//' || true)
  case "$parent_shell" in
    zsh)  echo "zsh"; return ;;
    bash) echo "bash"; return ;;
  esac
  case "${SHELL:-}" in
    */zsh)  echo "zsh" ;;
    */bash) echo "bash" ;;
    *)      echo "zsh" ;;
  esac
}

DETECTED_SHELL=$(detect_shell)
echo "Detected shell: $DETECTED_SHELL"

# --- Find kosh.py path (CWD first, then script dir, then rc file) ---

find_kosh_py() {
  # 1. Current directory (highest priority — user just ran setup here)
  if [[ -f "./kosh.py" ]]; then
    echo "$(pwd -P)/kosh.py"
    return
  fi

  # 2. Script's own directory
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  if [[ -f "$script_dir/kosh.py" ]]; then
    echo "$script_dir/kosh.py"
    return
  fi

  # 3. Existing symlink (if previously set up)
  if [[ -L "$KOSH_LINK" && -f "$KOSH_LINK" ]]; then
    readlink -f "$KOSH_LINK"
    return
  fi

  # 4. Check rc file for existing function/alias
  local rc_file="${1:-}"
  if [[ -n "$rc_file" && -f "$rc_file" ]]; then
    local func_path
    func_path=$(grep -A1 "^kosh()" "$rc_file" 2>/dev/null | grep -oE '/[^ "]+kosh\.py' | tail -1 || true)
    if [[ -n "$func_path" && -f "$func_path" ]]; then
      echo "$func_path"
      return
    fi
    local alias_path
    alias_path=$(grep -E "^alias kosh=" "$rc_file" 2>/dev/null | tail -1 | sed -E 's/.*uv run ([^"]+).*/\1/' | sed 's/[" ]//g' || true)
    if [[ -n "$alias_path" && -f "$alias_path" ]]; then
      echo "$alias_path"
      return
    fi
  fi

  return 1
}

# --- Create/update symlink ---

setup_symlink() {
  local target="$1"
  mkdir -p "$(dirname "$KOSH_LINK")"

  if [[ -L "$KOSH_LINK" ]]; then
    local current
    current=$(readlink -f "$KOSH_LINK" 2>/dev/null || true)
    if [[ "$current" == "$target" ]]; then
      echo "Symlink up to date: $KOSH_LINK -> $target"
      return
    fi
    echo "Updating symlink: $KOSH_LINK -> $target (was: $current)"
    ln -sf "$target" "$KOSH_LINK"
  else
    if [[ -f "$KOSH_LINK" ]]; then
      echo "Replacing file with symlink: $KOSH_LINK -> $target"
      rm -f "$KOSH_LINK"
    else
      echo "Creating symlink: $KOSH_LINK -> $target"
    fi
    ln -sf "$target" "$KOSH_LINK"
  fi
}

# --- Setup for zsh ---

setup_zsh() {
  local rc_file="${HOME}/.zshrc"
  local zfunc_dir="${HOME}/.zfunc"
  local comp_file="${zfunc_dir}/_kosh"

  KOSH_PY=$(find_kosh_py "$rc_file") || {
    echo "error: Cannot find kosh.py in current directory or script directory." >&2
    echo "  Run this from the directory containing kosh.py" >&2
    exit 1
  }
  echo "Found kosh.py: $KOSH_PY"

  # Create/update stable symlink
  setup_symlink "$KOSH_PY"

  # Generate zsh completions
  mkdir -p "$zfunc_dir"
  echo "Generating zsh completions..."
  uv run "$KOSH_PY" completions zsh > "$comp_file"

  # Fix: replace the guard that checks for kosh in PATH
  sed -i '' 's/(( ! $+commands\[kosh\] )) && return 1/# alias\/function compatible/' "$comp_file" 2>/dev/null || \
  sed -i 's/(( ! $+commands\[kosh\] )) && return 1/# alias\/function compatible/' "$comp_file"

  # Fix: replace bare "kosh" invocation with symlink path
  sed -i '' "s|COMP_CWORD=\$((CURRENT-1)) _KOSH_COMPLETE=zsh_complete kosh|COMP_CWORD=\$((CURRENT-1)) _KOSH_COMPLETE=zsh_complete uv run $KOSH_LINK|" "$comp_file" 2>/dev/null || \
  sed -i "s|COMP_CWORD=\$((CURRENT-1)) _KOSH_COMPLETE=zsh_complete kosh|COMP_CWORD=\$((CURRENT-1)) _KOSH_COMPLETE=zsh_complete uv run $KOSH_LINK|" "$comp_file"

  echo "Written: $comp_file"

  # Update .zshrc — always use the symlink path (never a hardcoded project path)
  local fpath_line='fpath=(~/.zfunc $fpath)'
  if ! grep -qF "$fpath_line" "$rc_file" 2>/dev/null; then
    echo "" >> "$rc_file"
    echo "# kosh CLI completions" >> "$rc_file"
    echo "$fpath_line" >> "$rc_file"
    echo "autoload -Uz compinit && compinit" >> "$rc_file"
    echo "Added fpath + compinit to $rc_file"
  else
    echo "fpath already configured in $rc_file"
  fi

  # Remove any old hardcoded kosh function/alias, replace with symlink-based one
  if grep -qE "^kosh\(\)" "$rc_file" 2>/dev/null; then
    # Check if it already points to the symlink
    if grep -A1 "^kosh()" "$rc_file" | grep -qF "$KOSH_LINK"; then
      echo "kosh() function already uses symlink"
    else
      echo "Updating kosh() function to use symlink..."
      sed -i '' '/^kosh()/,/^}/d' "$rc_file" 2>/dev/null || \
      sed -i '/^kosh()/,/^}/d' "$rc_file"
      echo "kosh() { uv run \"$KOSH_LINK\" \"\$@\"; }" >> "$rc_file"
      echo "Updated kosh() function in $rc_file"
    fi
  else
    # Comment out any alias, add function
    if grep -qE "^alias kosh=" "$rc_file" 2>/dev/null; then
      sed -i '' "s|^alias kosh=.*|# & # replaced by function below|" "$rc_file" 2>/dev/null || \
      sed -i "s|^alias kosh=.*|# & # replaced by function below|" "$rc_file"
    fi
    echo "kosh() { uv run \"$KOSH_LINK\" \"\$@\"; }" >> "$rc_file"
    echo "Added kosh() function to $rc_file (uses symlink)"
  fi

  echo ""
  echo "Done! Reload your shell:"
  echo "  exec zsh"
  echo ""
  echo "To switch kosh.py to a different directory:"
  echo "  ln -sf /path/to/new/kosh.py $KOSH_LINK"
}

# --- Setup for bash ---

setup_bash() {
  local rc_file="${HOME}/.bashrc"
  local comp_dir="${HOME}/.local/share/bash-completion/completions"
  local comp_file="${comp_dir}/kosh"

  KOSH_PY=$(find_kosh_py "$rc_file") || {
    echo "error: Cannot find kosh.py in current directory or script directory." >&2
    echo "  Run this from the directory containing kosh.py" >&2
    exit 1
  }
  echo "Found kosh.py: $KOSH_PY"

  # Create/update stable symlink
  setup_symlink "$KOSH_PY"

  # Generate bash completions
  mkdir -p "$comp_dir"
  echo "Generating bash completions..."
  uv run "$KOSH_PY" completions bash > "$comp_file"

  # Fix: replace bare "kosh" invocation with symlink path
  sed -i '' "s|_KOSH_COMPLETE=bash_complete kosh|_KOSH_COMPLETE=bash_complete uv run $KOSH_LINK|g" "$comp_file" 2>/dev/null || \
  sed -i "s|_KOSH_COMPLETE=bash_complete kosh|_KOSH_COMPLETE=bash_complete uv run $KOSH_LINK|g" "$comp_file"

  echo "Written: $comp_file"

  # Ensure kosh alias uses symlink
  # Remove old hardcoded alias/function
  sed -i '' '/^alias kosh=/d' "$rc_file" 2>/dev/null || sed -i '/^alias kosh=/d' "$rc_file"
  sed -i '' '/^kosh()/,/^}/d' "$rc_file" 2>/dev/null || sed -i '/^kosh()/,/^}/d' "$rc_file"

  if ! grep -qF "$KOSH_LINK" "$rc_file" 2>/dev/null; then
    echo "" >> "$rc_file"
    echo "# kosh CLI" >> "$rc_file"
    echo "alias kosh=\"uv run $KOSH_LINK\"" >> "$rc_file"
    echo "Added kosh alias to $rc_file (uses symlink)"
  fi

  # Source completions if bash-completion framework not detected
  local source_line="source \"$comp_file\""
  if ! grep -qF "$comp_file" "$rc_file" 2>/dev/null; then
    if ! grep -qE "(bash.completion|bash_completion)" "$rc_file" 2>/dev/null; then
      echo "" >> "$rc_file"
      echo "# kosh completions" >> "$rc_file"
      echo "[ -f \"$comp_file\" ] && $source_line" >> "$rc_file"
      echo "Added completion source to $rc_file"
    else
      echo "bash-completion framework detected (will auto-load from $comp_dir)"
    fi
  fi

  echo ""
  echo "Done! Reload your shell:"
  echo "  source ~/.bashrc"
  echo ""
  echo "To switch kosh.py to a different directory:"
  echo "  ln -sf /path/to/new/kosh.py $KOSH_LINK"
}

# --- Main ---

case "$DETECTED_SHELL" in
  zsh)  setup_zsh ;;
  bash) setup_bash ;;
  *)
    echo "error: Unsupported shell: $DETECTED_SHELL" >&2
    exit 1
    ;;
esac

echo ""
echo "To update completions after kosh.py changes:"
echo "  ./setup-kosh-completions.sh"
