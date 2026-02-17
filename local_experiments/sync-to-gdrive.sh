#!/usr/bin/env bash
# ============================================================================
# Sync Kagenti demo videos to Google Drive
#
# Uses a Google Cloud service account with Drive API access, scoped to a single
# shared folder. Only uploads/updates files — never deletes from Drive.
#
# USAGE:
#   # First time: show setup instructions
#   ./sync-to-gdrive.sh
#
#   # Sync all demos to Google Drive
#   ./sync-to-gdrive.sh --sync
#
#   # Sync only _latest files (smaller, faster)
#   ./sync-to-gdrive.sh --sync --latest-only
#
#   # Sync a specific category
#   ./sync-to-gdrive.sh --sync --category 02-ui-pages
#
#   # Dry run (show what would be synced)
#   ./sync-to-gdrive.sh --sync --dry-run
#
# CONFIGURATION:
#   Set these environment variables (or put them in .env):
#     GDRIVE_FOLDER_ID     - Google Drive folder ID to sync to
#     GDRIVE_SA_KEY_FILE   - Path to service account JSON key file
#
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMOS_DIR="$SCRIPT_DIR/demos"
ENV_FILE="$SCRIPT_DIR/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log_info()  { echo -e "${CYAN}[info]${NC} $*"; }
log_success() { echo -e "${GREEN}[ok]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
log_error() { echo -e "${RED}[error]${NC} $*"; }

# ── Parse arguments ─────────────────────────────────────────────────────
DO_SYNC=false
LATEST_ONLY=false
DRY_RUN=false
CATEGORY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sync)       DO_SYNC=true; shift ;;
        --latest-only) LATEST_ONLY=true; shift ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --category)   CATEGORY="$2"; shift 2 ;;
        -h|--help)    DO_SYNC=false; break ;;
        *)            echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Load .env ───────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# ── Show setup instructions if not configured or no --sync ──────────────
if [ "$DO_SYNC" = false ] || [ -z "${GDRIVE_FOLDER_ID:-}" ] || [ -z "${GDRIVE_SA_KEY_FILE:-}" ]; then
    cat << 'INSTRUCTIONS'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Google Drive Sync Setup
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 1: Create Google Cloud project and enable Drive API
  ────────────────────────────────────────────────────────

    # Create project (or use existing)
    gcloud projects create kagenti-demos --name="Kagenti Demos" 2>/dev/null || true
    gcloud config set project kagenti-demos

    # Enable the Drive API
    gcloud services enable drive.googleapis.com

  Step 2: Create a scoped service account
  ───────────────────────────────────────
    The service account uses drive.file scope — it can ONLY access files it
    creates or files explicitly shared with it. No access to anything else.

    # Create service account
    gcloud iam service-accounts create kagenti-demo-sync \
        --display-name="Kagenti Demo Video Sync" \
        --description="Syncs demo videos to a single Google Drive folder"

    # Get the service account email
    SA_EMAIL=$(gcloud iam service-accounts list \
        --filter="email:kagenti-demo-sync" --format="value(email)")
    echo "Service account: $SA_EMAIL"

    # Create and download the JSON key
    gcloud iam service-accounts keys create \
        ~/.config/kagenti-gdrive-sa.json \
        --iam-account="$SA_EMAIL"

    echo "Key saved to: ~/.config/kagenti-gdrive-sa.json"

  Step 3: Create a Google Drive folder and share with service account
  ──────────────────────────────────────────────────────────────────
    1. Create a folder in Google Drive (e.g., "Kagenti Demos")
    2. Right-click → Share → add the service account email:
         kagenti-demo-sync@kagenti-demos.iam.gserviceaccount.com
    3. Give it "Editor" access
    4. Copy the folder ID from the URL:
         https://drive.google.com/drive/folders/FOLDER_ID_HERE
                                                ^^^^^^^^^^^^^^

    The service account can ONLY touch files inside this shared folder.

  Step 4: Configure environment
  ─────────────────────────────
    Add to .env (or export):

      GDRIVE_FOLDER_ID=your-folder-id-here
      GDRIVE_SA_KEY_FILE=~/.config/kagenti-gdrive-sa.json

  Step 5: Install Python dependency
  ──────────────────────────────────
    uv pip install google-api-python-client google-auth

  Step 6: Run sync
  ────────────────
    # Sync all demos
    ./sync-to-gdrive.sh --sync

    # Sync only latest versions (faster)
    ./sync-to-gdrive.sh --sync --latest-only

    # Dry run first
    ./sync-to-gdrive.sh --sync --dry-run

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INSTRUCTIONS

    if [ -z "${GDRIVE_FOLDER_ID:-}" ]; then
        log_warn "GDRIVE_FOLDER_ID not set"
    else
        log_success "GDRIVE_FOLDER_ID=$GDRIVE_FOLDER_ID"
    fi
    if [ -z "${GDRIVE_SA_KEY_FILE:-}" ]; then
        log_warn "GDRIVE_SA_KEY_FILE not set"
    elif [ ! -f "${GDRIVE_SA_KEY_FILE}" ]; then
        log_error "GDRIVE_SA_KEY_FILE not found: $GDRIVE_SA_KEY_FILE"
    else
        log_success "GDRIVE_SA_KEY_FILE=$GDRIVE_SA_KEY_FILE"
    fi
    exit 0
fi

# ── Validate config ─────────────────────────────────────────────────────
if [ ! -f "$GDRIVE_SA_KEY_FILE" ]; then
    log_error "Service account key file not found: $GDRIVE_SA_KEY_FILE"
    log_info "Run without --sync to see setup instructions"
    exit 1
fi

if [ ! -d "$DEMOS_DIR" ]; then
    log_error "Demos directory not found: $DEMOS_DIR"
    exit 1
fi

# ── Build file list ─────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}┃${NC} Google Drive Sync"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

SYNC_DIR="$DEMOS_DIR"
if [ -n "$CATEGORY" ]; then
    SYNC_DIR="$DEMOS_DIR/$CATEGORY"
    if [ ! -d "$SYNC_DIR" ]; then
        log_error "Category directory not found: $SYNC_DIR"
        exit 1
    fi
    log_info "Syncing category: $CATEGORY"
fi

# Collect files to sync
FILE_LIST=$(mktemp)
trap "rm -f $FILE_LIST" EXIT

if [ "$LATEST_ONLY" = true ]; then
    find "$SYNC_DIR" -name "*_latest*" -type f > "$FILE_LIST"
    # Also include metadata files (timestamps, narration, spec)
    find "$SYNC_DIR" -name "*.json" -o -name "*.txt" -o -name "*.spec.ts" >> "$FILE_LIST" 2>/dev/null
else
    find "$SYNC_DIR" -type f \
        \( -name "*.webm" -o -name "*.mp4" -o -name "*.mp3" \
           -o -name "*.json" -o -name "*.txt" -o -name "*.spec.ts" \) > "$FILE_LIST"
fi

FILE_COUNT=$(wc -l < "$FILE_LIST" | tr -d ' ')
TOTAL_SIZE=$(cat "$FILE_LIST" | xargs -I{} stat -f%z "{}" 2>/dev/null | awk '{s+=$1}END{printf "%.1f", s/1048576}')

log_info "Files to sync: $FILE_COUNT ($TOTAL_SIZE MB)"
if [ "$LATEST_ONLY" = true ]; then
    log_info "Mode: latest-only (skipping timestamped versions)"
fi
if [ "$DRY_RUN" = true ]; then
    log_info "Mode: dry-run (no uploads)"
fi
echo ""

# Show what will be synced
while IFS= read -r file; do
    rel_path="${file#$DEMOS_DIR/}"
    size=$(stat -f%z "$file" 2>/dev/null | awk '{printf "%.1f", $1/1048576}')
    if [ "$DRY_RUN" = true ]; then
        echo "  [dry-run] $rel_path (${size}MB)"
    fi
done < "$FILE_LIST"

if [ "$DRY_RUN" = true ]; then
    echo ""
    log_info "Dry run complete. Use --sync without --dry-run to upload."
    exit 0
fi

# ── Execute sync via Python ─────────────────────────────────────────────
log_info "Starting upload to Google Drive folder: $GDRIVE_FOLDER_ID"
echo ""

export SYNC_DIR="$SYNC_DIR"
export FILE_LIST="$FILE_LIST"
uv run --with google-api-python-client --with google-auth python3 - << 'PYEOF'
import json
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SA_KEY = os.environ["GDRIVE_SA_KEY_FILE"]
ROOT_FOLDER_ID = os.environ["GDRIVE_FOLDER_ID"]
DEMOS_DIR = os.environ.get("SYNC_DIR", "demos")
FILE_LIST = os.environ.get("FILE_LIST", "")

GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
YELLOW = "\033[1;33m"
NC = "\033[0m"

# Authenticate
creds = service_account.Credentials.from_service_account_file(SA_KEY, scopes=SCOPES)
service = build("drive", "v3", credentials=creds)

# Cache of folder_path -> folder_id
folder_cache = {"/": ROOT_FOLDER_ID}

def ensure_folder(path_parts):
    """Create nested folder structure on Drive, return leaf folder ID."""
    current_path = "/"
    parent_id = ROOT_FOLDER_ID
    for part in path_parts:
        current_path = f"{current_path}{part}/"
        if current_path in folder_cache:
            parent_id = folder_cache[current_path]
            continue
        # Search for existing folder
        query = (
            f"name='{part}' and '{parent_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        if results.get("files"):
            folder_id = results["files"][0]["id"]
        else:
            # Create folder
            meta = {
                "name": part,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = service.files().create(body=meta, fields="id").execute()
            folder_id = folder["id"]
            print(f"  {CYAN}[mkdir]{NC} {current_path}")
        folder_cache[current_path] = folder_id
        parent_id = folder_id
    return parent_id

def get_mime_type(filename):
    ext = Path(filename).suffix.lower()
    return {
        ".webm": "video/webm",
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".json": "application/json",
        ".txt": "text/plain",
        ".ts": "text/plain",
    }.get(ext, "application/octet-stream")

# Read file list
demos_dir = Path(DEMOS_DIR)
with open(FILE_LIST) as f:
    files = [line.strip() for line in f if line.strip()]

uploaded = 0
skipped = 0

for filepath in files:
    p = Path(filepath)
    rel = p.relative_to(demos_dir)
    folder_parts = list(rel.parent.parts)
    filename = rel.name

    # Ensure folder exists on Drive
    parent_id = ensure_folder(folder_parts) if folder_parts else ROOT_FOLDER_ID

    # Check if file already exists (by name in folder)
    query = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
    existing = service.files().list(q=query, fields="files(id,size)").execute()

    file_size = p.stat().st_size
    mime = get_mime_type(filename)

    if existing.get("files"):
        # Update existing file
        file_id = existing["files"][0]["id"]
        remote_size = int(existing["files"][0].get("size", 0))
        if remote_size == file_size:
            skipped += 1
            continue
        media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
        service.files().update(fileId=file_id, media_body=media).execute()
        size_mb = file_size / 1048576
        print(f"  {YELLOW}[update]{NC} {rel} ({size_mb:.1f}MB)")
    else:
        # Create new file
        meta = {"name": filename, "parents": [parent_id]}
        media = MediaFileUpload(str(p), mimetype=mime, resumable=True)
        service.files().create(body=meta, media_body=media, fields="id").execute()
        size_mb = file_size / 1048576
        print(f"  {GREEN}[upload]{NC} {rel} ({size_mb:.1f}MB)")
    uploaded += 1

print()
print(f"  {GREEN}Uploaded: {uploaded} files{NC}")
if skipped:
    print(f"  {CYAN}Skipped: {skipped} files (unchanged){NC}")
PYEOF

SYNC_EXIT=$?

echo ""
if [ $SYNC_EXIT -eq 0 ]; then
    log_success "Sync complete!"
    log_info "View at: https://drive.google.com/drive/folders/$GDRIVE_FOLDER_ID"
else
    log_error "Sync failed (exit code $SYNC_EXIT)"
    log_info "Run without --sync to see setup instructions"
fi

exit $SYNC_EXIT
