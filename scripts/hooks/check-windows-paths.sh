#!/usr/bin/env bash
# Pre-commit hook: warn about Windows-incompatible filenames
#
# Kagenti uses colons in skill folder names (e.g., .claude/skills/auth:keycloak-confidential-client/).
# These are valid on Linux/macOS but not on native Windows filesystems.
# Windows users must use WSL — see docs/developer/windows-wsl-setup.md

set -euo pipefail

# Windows-forbidden characters (excluding / which is a path separator on all platforms):
# < > : " \ | ? *
FORBIDDEN_PATTERN='[<>"\\|?*]'

bad_files=()
while IFS= read -r -d '' file; do
    # Check the full path so directory components are validated too.
    # Strip colons first — they are intentional in skill folder names
    # (e.g., .claude/skills/auth:keycloak-confidential-client/).
    cleaned=${file//:/}
    if [[ "$cleaned" =~ $FORBIDDEN_PATTERN ]]; then
        bad_files+=("$file")
    fi
done < <(git ls-files -z)

if [[ ${#bad_files[@]} -gt 0 ]]; then
    echo "ERROR: Found filenames with Windows-forbidden characters (excluding colons):"
    for f in "${bad_files[@]}"; do
        echo "  $f"
    done
    echo ""
    echo "Note: Colons in .claude/skills/ folder names are intentional and supported via WSL."
    echo "See docs/developer/windows-wsl-setup.md for Windows setup instructions."
    exit 1
fi
