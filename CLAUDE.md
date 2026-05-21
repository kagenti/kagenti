Done. The fix is applied on branch `fix/docs-feature-flag-endpoint-path`:

- **File**: `CLAUDE.md` line 184
- **Change**: `GET /api/config/features` → `GET /api/v1/config/features`

This matches the actual route prefix in `main.py` where the config router is included with `prefix="/api/v1"`. Would you like me to push and create a PR?
