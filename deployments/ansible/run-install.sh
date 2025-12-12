#!/usr/bin/env bash
set -euo pipefail
# Small wrapper to simplify running the Kagenti Ansible installer playbook.
#
# Features:
# - Accepts an --env shorthand (dev|minimal|ocp) that maps to files in ../envs
# - Allows passing an explicit --env-file (can be specified multiple times)
# - Accepts --secret to point to a secret values file
# - Toggles kind preload via --preload and disables kind creation via --no-kind
# - Passes any additional args through to ansible-playbook
#
# Usage examples:
#   ./run-install.sh --env dev
#   ./run-install.sh --env ocp --secret ../envs/.secret_values.yaml
#   ./run-install.sh --env dev --preload --extra-vars '{"kind_images_preload": true}'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK="$SCRIPT_DIR/installer-playbook.yml"

if [[ ! -f "$PLAYBOOK" ]]; then
  echo "ERROR: playbook not found at $PLAYBOOK" >&2
  exit 2
fi

ENV_FILES=()
# Default secrets file (relative to the script/playbook directory). If the
# user passes --secret this value will be overridden.
SECRET_FILE="$SCRIPT_DIR/../envs/.secret_values.yaml"
# Track whether the user explicitly provided --secret so we can fail early
# on a missing file vs. warn+skip when the default is missing.
SECRET_PROVIDED=false
EXTRA_VARS=""
ANSIBLE_ADDITIONAL_ARGS=()

usage() {
  cat <<EOF
Usage: ${0##*/} [options] [-- ansible-playbook-args]

Options:
  --env <dev|minimal|auth|barebones|ocp>   Use a named environment file from deployments/envs
  --env-file <path>         Add an explicit environment values file (can repeat)
  --secret <path>           Path to secret values file (example: ../envs/.secret_values.yaml)
  --preload                 Set kind_images_preload=true
  --no-kind                 Set create_kind_cluster=false
  --extra-vars '<JSON>'     Extra-vars (JSON/YAML) to pass to ansible-playbook
  -h, --help                Show this help

Any arguments after -- are passed directly to ansible-playbook.

Examples:
  ${0##*/} --env dev
  ${0##*/} --env ocp --secret ../envs/.secret_values.yaml
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      shift
      [[ $# -gt 0 ]] || { echo "--env requires a value"; exit 2; }
      case "$1" in
        dev) ENV_FILES+=("$SCRIPT_DIR/../envs/dev_values.yaml") ;;
        minimal) ENV_FILES+=("$SCRIPT_DIR/../envs/dev_values_minimal.yaml") ;;
        auth) ENV_FILES+=("$SCRIPT_DIR/../envs/dev_values_minimal_auth.yaml") ;;
        barebones) ENV_FILES+=("$SCRIPT_DIR/../envs/barebones_operator_values.yaml") ;;
        ocp) ENV_FILES+=("$SCRIPT_DIR/../envs/ocp_values.yaml") ;;
        *) echo "Unknown env: $1" >&2; exit 2 ;;
      esac
      shift
      ;;
    --env-file)
      shift
      [[ $# -gt 0 ]] || { echo "--env-file requires a value"; exit 2; }
      ENV_FILES+=("$1")
      shift
      ;;
    --secret)
      shift
      [[ $# -gt 0 ]] || { echo "--secret requires a value"; exit 2; }
      SECRET_FILE="$1"
      SECRET_PROVIDED=true
      shift
      ;;
    --preload)
      EXTRA_PRELOAD=true
      shift
      ;;
    --no-kind)
      EXTRA_NOKIND=true
      shift
      ;;
    --extra-vars)
      shift
      [[ $# -gt 0 ]] || { echo "--extra-vars requires a value"; exit 2; }
      EXTRA_VARS="$1"
      shift
      ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift
      ANSIBLE_ADDITIONAL_ARGS+=("$@")
      break
      ;;
    *)
      # treat unknown args as ansible-playbook args
      ANSIBLE_ADDITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

# Build the primary extra-vars JSON object to pass via -e. We must pass
# structured JSON (not key=value with raw quotes) so Ansible receives lists
# as list types rather than strings (avoids iterating over characters).
declare -a JSON_ENTRIES=()

if [[ ${#ENV_FILES[@]} -gt 0 ]]; then
  # Resolve env file paths to absolute paths and validate they exist.
  declare -a RESOLVED_ENV_FILES=()
  for ef in "${ENV_FILES[@]}"; do
    if [[ "$ef" = /* ]]; then
      resolved="$ef"
    else
      # Resolve --env-file relative to the current working directory (PWD)
      # rather than the script directory so users can pass paths from where
      # they invoke the script.
      resolved="$(cd "$(dirname "$ef")" >/dev/null 2>&1 && echo "$(pwd)/$(basename "$ef")")"
    fi
    if [[ ! -f "$resolved" ]]; then
      echo "ERROR: global value file not found: $resolved" >&2
      exit 2
    fi
    RESOLVED_ENV_FILES+=("$resolved")
  done

  # convert to JSON array with the resolved absolute paths
  json_list="["
  first=true
  for resolved in "${RESOLVED_ENV_FILES[@]}"; do
    if [[ "$first" = true ]]; then
      json_list+="\"$resolved\""
      first=false
    else
      json_list+=",\"$resolved\""
    fi
  done
  json_list+="]"
  JSON_ENTRIES+=("\"global_value_files\": $json_list")
fi

if [[ -n "$SECRET_FILE" ]]; then
  # resolve relative to script dir when relative
  if [[ "$SECRET_FILE" = /* ]]; then
    secret_resolved="$SECRET_FILE"
  else
    secret_resolved="$(cd "$SCRIPT_DIR" && cd "$(dirname "$SECRET_FILE")" >/dev/null 2>&1 && echo "$(pwd)/$(basename "$SECRET_FILE")")"
  fi

  # Check existence: if the user explicitly provided --secret and the file
  # is missing, fail early. If we're using the default and it's missing,
  # warn and skip adding the secret (the playbook will behave accordingly).
  if [[ -f "$secret_resolved" ]]; then
    JSON_ENTRIES+=("\"secret_values_file\": \"$secret_resolved\"")
  else
    if [[ "$SECRET_PROVIDED" = true ]]; then
      echo "ERROR: secret values file specified but not found: $secret_resolved" >&2
      exit 2
    else
      echo "WARNING: default secret values file not found at $secret_resolved; continuing without secrets." >&2
    fi
  fi
fi

if [[ ${EXTRA_PRELOAD:-false} = true ]]; then
  JSON_ENTRIES+=("\"kind_images_preload\": true")
fi

if [[ ${EXTRA_NOKIND:-false} = true ]]; then
  JSON_ENTRIES+=("\"create_kind_cluster\": false")
fi

# macOS SSL certificate fix: Set SSL environment variables to use certifi bundle
# This fixes "CERTIFICATE_VERIFY_FAILED" errors when Ansible tries to fetch HTTPS resources
if [[ "$(uname)" == "Darwin" ]]; then
  # Try to find certifi certificates using Python
  if command -v python3 >/dev/null 2>&1; then
    CERTIFI_PATH=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null || echo "")
    if [[ -n "$CERTIFI_PATH" && -f "$CERTIFI_PATH" ]]; then
      export SSL_CERT_FILE="$CERTIFI_PATH"
      export REQUESTS_CA_BUNDLE="$CERTIFI_PATH"
      echo "macOS detected: Setting SSL_CERT_FILE to $CERTIFI_PATH"
    else
      echo "WARNING: macOS detected but certifi not found. Installing certifi..." >&2
      # Try to install certifi using uv or pip
      if command -v uv >/dev/null 2>&1; then
        uv pip install --upgrade certifi >/dev/null 2>&1 || true
      else
        python3 -m pip install --upgrade certifi >/dev/null 2>&1 || true
      fi
      # Try again to get the path
      CERTIFI_PATH=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null || echo "")
      if [[ -n "$CERTIFI_PATH" && -f "$CERTIFI_PATH" ]]; then
        export SSL_CERT_FILE="$CERTIFI_PATH"
        export REQUESTS_CA_BUNDLE="$CERTIFI_PATH"
        echo "macOS detected: Installed certifi and set SSL_CERT_FILE to $CERTIFI_PATH"
      else
        echo "WARNING: Could not configure SSL certificates for macOS. You may encounter SSL errors." >&2
        echo "         To fix manually, run: python3 -m pip install --upgrade certifi" >&2
      fi
    fi
  fi
fi

# Call ansible-playbook via the 'uv' wrapper when available so uv manages deps/venv.
# Fall back to ansible-playbook if uv is not present.
if command -v uv >/dev/null 2>&1; then
  ANSIBLE_CMD=(uv run ansible-playbook -i localhost, -c local "$PLAYBOOK")
else
  echo "WARNING: 'uv' not found in PATH; falling back to 'ansible-playbook'. To use uv ensure it's installed and on PATH." >&2
  ANSIBLE_CMD=(ansible-playbook -i localhost, -c local "$PLAYBOOK")
fi

if [[ ${#JSON_ENTRIES[@]} -gt 0 ]]; then
  # Join entries into a single JSON object
  json_payload="{"
  first=true
  for e in "${JSON_ENTRIES[@]}"; do
    if [[ "$first" = true ]]; then
      json_payload+="$e"
      first=false
    else
      json_payload+=",$e"
    fi
  done
  json_payload+="}"
  ANSIBLE_CMD+=( -e "$json_payload" )
fi

if [[ -n "$EXTRA_VARS" ]]; then
  # pass user-provided extra-vars (they will override earlier values if keys clash)
  ANSIBLE_CMD+=( -e "$EXTRA_VARS" )
fi

if [[ ${#ANSIBLE_ADDITIONAL_ARGS[@]} -gt 0 ]]; then
  ANSIBLE_CMD+=( "${ANSIBLE_ADDITIONAL_ARGS[@]}" )
fi

# Prepare a redacted display copy of the command to avoid leaking secret
# file paths (e.g. secret values file) into logs. We still execute the full
# command below, but only show a redacted version here.
DISPLAY_CMD=("${ANSIBLE_CMD[@]}")
if [[ -n "${secret_resolved:-}" ]]; then
  for i in "${!DISPLAY_CMD[@]}"; do
    # redact any argument that contains the resolved secret path
    if [[ "${DISPLAY_CMD[$i]}" == *"$secret_resolved"* ]]; then
      DISPLAY_CMD[$i]="<REDACTED_SECRET_FILE>"
      continue
    fi
    # also redact any argument that looks like a secret filename
    if [[ "${DISPLAY_CMD[$i]}" == *".secret"* || "${DISPLAY_CMD[$i]}" == *"secret_values"* || "${DISPLAY_CMD[$i]}" == *"secret"* ]]; then
      DISPLAY_CMD[$i]="<REDACTED_SECRET_FILE>"
    fi
  done
fi

echo "Running: ${DISPLAY_CMD[*]}"

# Run the ansible-playbook command and capture its exit status so we can
# perform follow-up actions (like printing Helm release notes) after it
# completes. We avoid 'exec' so the script can continue.
"${ANSIBLE_CMD[@]}"
rc=$?

if [[ $rc -ne 0 ]]; then
  echo "ERROR: ansible-playbook exited with status $rc" >&2
  exit $rc
fi

# print helm release notes at the end
if command -v helm >/dev/null 2>&1; then
  printf "\n=== Helm release notes for 'kagenti' (namespace: kagenti-system) ===\n"
  if ! helm get notes -n kagenti-system kagenti; then
    echo "WARNING: failed to fetch helm release notes for 'kagenti' in namespace 'kagenti-system'" >&2
  fi
else
  echo "WARNING: 'helm' not found in PATH; skipping 'helm get notes'" >&2
fi

exit 0
