#!/usr/bin/env bash
set -euo pipefail

# Automates Keycloak configuration for GitHub login in an OpenShell tenant.
# Reproduces the manual steps from HOW_TO_KOSH_GITHUB.md via Keycloak Admin REST API.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
REALM="openshell"
KEYCLOAK_NS="keycloak"
GROUP_NAME="openshell-users"
CLIENT_ID_NAME="openshell-cli"
IDP_ALIAS="github"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Configures Keycloak (openshell realm) to use GitHub as an identity provider.
Creates the authorization group, attribute mappers, and disables VERIFY_PROFILE.

REQUIRED:
  --github-client-id ID       GitHub OAuth App Client ID (from github.com/settings/developers)
  --github-client-secret SEC  GitHub OAuth App Client Secret

OPTIONS:
  --keycloak-url URL          Keycloak base URL (default: auto-detect from cluster)
  --realm REALM               Keycloak realm (default: openshell)
  --group NAME                Authorization group name (default: openshell-users)
  --client NAME               OIDC client name (default: openshell-cli)
  --idp-alias ALIAS           Identity provider alias (default: github)
  --verify-only               Only verify existing configuration, don't create/modify
  --dry-run                   Print API calls without executing
  -h, --help                  Show this help

ENVIRONMENT:
  KUBECONFIG                  Path to kubeconfig (required for admin credential retrieval)

EXAMPLE:
  # Full setup
  KUBECONFIG=.kube/config-ykt1 ./scripts/kosh-github-keycloak-setup.sh \\
    --github-client-id Ov23liXXXXXXXXXX \\
    --github-client-secret ghsec_XXXXXXXX

  # Verify existing setup
  KUBECONFIG=.kube/config-ykt1 ./scripts/kosh-github-keycloak-setup.sh --verify-only

WHAT THIS SCRIPT DOES:
  1. Adds GitHub as an Identity Provider (with user:email read:user scopes)
  2. Creates attribute mappers: first-name, email, username
  3. Disables VERIFY_PROFILE required action
  4. Creates "$GROUP_NAME" group
  5. Adds group membership mapper to $CLIENT_ID_NAME client
  6. Verifies all components are configured correctly
EOF
    exit "${1:-0}"
}

# --- Argument parsing ---
GITHUB_CLIENT_ID=""
GITHUB_CLIENT_SECRET=""
KEYCLOAK_URL=""
VERIFY_ONLY=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --github-client-id) GITHUB_CLIENT_ID="$2"; shift 2 ;;
        --github-client-secret) GITHUB_CLIENT_SECRET="$2"; shift 2 ;;
        --keycloak-url) KEYCLOAK_URL="$2"; shift 2 ;;
        --realm) REALM="$2"; shift 2 ;;
        --group) GROUP_NAME="$2"; shift 2 ;;
        --client) CLIENT_ID_NAME="$2"; shift 2 ;;
        --idp-alias) IDP_ALIAS="$2"; shift 2 ;;
        --verify-only) VERIFY_ONLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) usage 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "$VERIFY_ONLY" == "false" ]]; then
    if [[ -z "$GITHUB_CLIENT_ID" || -z "$GITHUB_CLIENT_SECRET" ]]; then
        echo "ERROR: --github-client-id and --github-client-secret are required" >&2
        echo "" >&2
        echo "Create a GitHub OAuth App at https://github.com/settings/developers" >&2
        echo "  Callback URL: https://<keycloak-host>/realms/$REALM/broker/$IDP_ALIAS/endpoint" >&2
        echo "" >&2
        usage 1
    fi
fi

# --- Helper functions ---
log() { echo -e "\033[0;34m→\033[0m $*"; }
ok()  { echo -e "\033[0;32m✓\033[0m $*"; }
err() { echo -e "\033[0;31m✗\033[0m $*" >&2; }
warn() { echo -e "\033[0;33m!\033[0m $*"; }

api_call() {
    local method="$1" path="$2"
    shift 2
    local url="${KEYCLOAK_URL}${path}"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [dry-run] $method $url" >&2
        return 0
    fi
    curl -sf -X "$method" "$url" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "$@"
}

api_call_status() {
    local method="$1" path="$2"
    shift 2
    local url="${KEYCLOAK_URL}${path}"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [dry-run] $method $url" >&2
        echo "200"
        return 0
    fi
    curl -s -o /dev/null -w "%{http_code}" -X "$method" "$url" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "$@"
}

# --- Detect Keycloak URL ---
if [[ -z "$KEYCLOAK_URL" ]]; then
    if ! command -v kubectl &>/dev/null; then
        echo "ERROR: kubectl not found and --keycloak-url not set" >&2
        exit 1
    fi
    CLUSTER_DOMAIN=$(kubectl get ingress.config.openshift.io cluster -o jsonpath='{.spec.domain}' 2>/dev/null || true)
    if [[ -z "$CLUSTER_DOMAIN" ]]; then
        CLUSTER_DOMAIN=$(kubectl get route -n "$KEYCLOAK_NS" keycloak -o jsonpath='{.spec.host}' 2>/dev/null | sed 's/^keycloak-keycloak\.//')
    fi
    if [[ -z "$CLUSTER_DOMAIN" ]]; then
        echo "ERROR: Cannot auto-detect cluster domain. Set --keycloak-url" >&2
        exit 1
    fi
    KEYCLOAK_URL="https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}"
fi

log "Keycloak URL: $KEYCLOAK_URL"
log "Realm: $REALM"

# --- Get admin token ---
log "Obtaining admin token..."
KC_USER=$(kubectl get secret keycloak-initial-admin -n "$KEYCLOAK_NS" -o jsonpath='{.data.username}' | base64 -d)
KC_PASS=$(kubectl get secret keycloak-initial-admin -n "$KEYCLOAK_NS" -o jsonpath='{.data.password}' | base64 -d)

TOKEN=$(curl -sf "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli" \
    -d "username=$KC_USER" \
    -d "password=$KC_PASS" \
    -d "grant_type=password" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

if [[ -z "$TOKEN" ]]; then
    err "Failed to obtain admin token"
    exit 1
fi
ok "Admin token obtained"

ADMIN_API="/admin/realms/$REALM"

# --- Verify realm exists ---
REALM_CHECK=$(api_call_status GET "$ADMIN_API")
if [[ "$REALM_CHECK" != "200" ]]; then
    err "Realm '$REALM' not found (HTTP $REALM_CHECK)"
    exit 1
fi
ok "Realm '$REALM' exists"

# ============================================================
# Step 1: GitHub Identity Provider
# ============================================================
setup_idp() {
    log "Configuring GitHub Identity Provider (alias: $IDP_ALIAS)..."

    local existing_status
    existing_status=$(api_call_status GET "$ADMIN_API/identity-provider/instances/$IDP_ALIAS")

    if [[ "$existing_status" == "200" ]]; then
        warn "IdP '$IDP_ALIAS' already exists — updating"
        local status
        status=$(api_call_status PUT "$ADMIN_API/identity-provider/instances/$IDP_ALIAS" \
            -d "$(cat <<IDPJSON
{
    "alias": "$IDP_ALIAS",
    "providerId": "github",
    "enabled": true,
    "trustEmail": true,
    "firstBrokerLoginFlowAlias": "first broker login",
    "config": {
        "clientId": "$GITHUB_CLIENT_ID",
        "clientSecret": "$GITHUB_CLIENT_SECRET",
        "defaultScope": "user:email read:user",
        "syncMode": "IMPORT"
    }
}
IDPJSON
)")
        if [[ "$status" == "204" || "$DRY_RUN" == "true" ]]; then
            ok "IdP '$IDP_ALIAS' updated"
        else
            err "Failed to update IdP (HTTP $status)"
            return 1
        fi
    else
        local status
        status=$(api_call_status POST "$ADMIN_API/identity-provider/instances" \
            -d "$(cat <<IDPJSON
{
    "alias": "$IDP_ALIAS",
    "providerId": "github",
    "enabled": true,
    "trustEmail": true,
    "firstBrokerLoginFlowAlias": "first broker login",
    "config": {
        "clientId": "$GITHUB_CLIENT_ID",
        "clientSecret": "$GITHUB_CLIENT_SECRET",
        "defaultScope": "user:email read:user",
        "syncMode": "IMPORT"
    }
}
IDPJSON
)")
        if [[ "$status" == "201" || "$DRY_RUN" == "true" ]]; then
            ok "IdP '$IDP_ALIAS' created"
        else
            err "Failed to create IdP (HTTP $status)"
            return 1
        fi
    fi
}

# ============================================================
# Step 2: Attribute Mappers
# ============================================================
setup_mappers() {
    log "Configuring IdP attribute mappers..."

    local mappers
    mappers=$(api_call GET "$ADMIN_API/identity-provider/instances/$IDP_ALIAS/mappers" 2>/dev/null || echo "[]")

    create_or_update_mapper() {
        local name="$1" json="$2"
        local existing_id
        existing_id=$(echo "$mappers" | python3 -c "
import sys, json
ms = json.load(sys.stdin)
for m in ms:
    if m['name'] == '$name':
        print(m['id'])
        break
" 2>/dev/null || true)

        if [[ -n "$existing_id" ]]; then
            local status
            status=$(api_call_status PUT "$ADMIN_API/identity-provider/instances/$IDP_ALIAS/mappers/$existing_id" \
                -d "$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); d['id']='$existing_id'; print(json.dumps(d))")")
            if [[ "$status" == "204" || "$DRY_RUN" == "true" ]]; then
                ok "  Mapper '$name' updated"
            else
                err "  Failed to update mapper '$name' (HTTP $status)"
            fi
        else
            local status
            status=$(api_call_status POST "$ADMIN_API/identity-provider/instances/$IDP_ALIAS/mappers" -d "$json")
            if [[ "$status" == "201" || "$DRY_RUN" == "true" ]]; then
                ok "  Mapper '$name' created"
            else
                err "  Failed to create mapper '$name' (HTTP $status)"
            fi
        fi
    }

    # Mapper: first-name (GitHub "name" → firstName)
    create_or_update_mapper "first-name" '{
        "name": "first-name",
        "identityProviderAlias": "'"$IDP_ALIAS"'",
        "identityProviderMapper": "github-user-attribute-mapper",
        "config": {
            "syncMode": "INHERIT",
            "jsonField": "name",
            "userAttribute": "firstName"
        }
    }'

    # Mapper: email
    create_or_update_mapper "email" '{
        "name": "email",
        "identityProviderAlias": "'"$IDP_ALIAS"'",
        "identityProviderMapper": "github-user-attribute-mapper",
        "config": {
            "syncMode": "INHERIT",
            "jsonField": "email",
            "userAttribute": "email"
        }
    }'

    # Mapper: username
    create_or_update_mapper "username" '{
        "name": "username",
        "identityProviderAlias": "'"$IDP_ALIAS"'",
        "identityProviderMapper": "github-user-attribute-mapper",
        "config": {
            "syncMode": "INHERIT",
            "jsonField": "login",
            "userAttribute": "username"
        }
    }'
}

# ============================================================
# Step 3: Disable VERIFY_PROFILE
# ============================================================
disable_verify_profile() {
    log "Disabling VERIFY_PROFILE required action..."

    local actions
    actions=$(api_call GET "$ADMIN_API/authentication/required-actions" 2>/dev/null || echo "[]")

    local vp_enabled
    vp_enabled=$(echo "$actions" | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    if a['alias'] == 'VERIFY_PROFILE':
        print('true' if a.get('enabled', False) else 'false')
        break
else:
    print('not_found')
" 2>/dev/null || echo "error")

    if [[ "$vp_enabled" == "false" ]]; then
        ok "VERIFY_PROFILE already disabled"
        return 0
    fi

    if [[ "$vp_enabled" == "not_found" ]]; then
        warn "VERIFY_PROFILE action not found — may already be removed"
        return 0
    fi

    local status
    status=$(api_call_status PUT "$ADMIN_API/authentication/required-actions/VERIFY_PROFILE" \
        -d '{
            "alias": "VERIFY_PROFILE",
            "name": "Verify Profile",
            "providerId": "VERIFY_PROFILE",
            "enabled": false,
            "defaultAction": false,
            "priority": 90
        }')

    if [[ "$status" == "204" || "$DRY_RUN" == "true" ]]; then
        ok "VERIFY_PROFILE disabled"
    else
        err "Failed to disable VERIFY_PROFILE (HTTP $status)"
    fi
}

# ============================================================
# Step 4: Create openshell-users group
# ============================================================
setup_group() {
    log "Ensuring group '$GROUP_NAME' exists..."

    local groups
    groups=$(api_call GET "$ADMIN_API/groups?search=$GROUP_NAME&exact=true" 2>/dev/null || echo "[]")

    local group_id
    group_id=$(echo "$groups" | python3 -c "
import sys, json
gs = json.load(sys.stdin)
for g in gs:
    if g['name'] == '$GROUP_NAME':
        print(g['id'])
        break
" 2>/dev/null || true)

    if [[ -n "$group_id" ]]; then
        ok "Group '$GROUP_NAME' already exists (id: ${group_id:0:8}...)"
    else
        local status
        status=$(api_call_status POST "$ADMIN_API/groups" \
            -d "{\"name\": \"$GROUP_NAME\"}")
        if [[ "$status" == "201" || "$DRY_RUN" == "true" ]]; then
            ok "Group '$GROUP_NAME' created"
        else
            err "Failed to create group (HTTP $status)"
        fi
    fi
}

# ============================================================
# Step 5: Group membership mapper on client
# ============================================================
setup_group_mapper() {
    log "Configuring group membership mapper on client '$CLIENT_ID_NAME'..."

    # Find client UUID
    local clients
    clients=$(api_call GET "$ADMIN_API/clients?clientId=$CLIENT_ID_NAME" 2>/dev/null || echo "[]")

    local client_uuid
    client_uuid=$(echo "$clients" | python3 -c "
import sys, json
cs = json.load(sys.stdin)
if cs:
    print(cs[0]['id'])
" 2>/dev/null || true)

    if [[ -z "$client_uuid" ]]; then
        err "Client '$CLIENT_ID_NAME' not found"
        return 1
    fi

    # Check existing mappers on the client
    local client_mappers
    client_mappers=$(api_call GET "$ADMIN_API/clients/$client_uuid/protocol-mappers/models" 2>/dev/null || echo "[]")

    local existing_mapper_id
    existing_mapper_id=$(echo "$client_mappers" | python3 -c "
import sys, json
for m in json.load(sys.stdin):
    if m['name'] == 'groups':
        print(m['id'])
        break
" 2>/dev/null || true)

    local mapper_json='{
        "name": "groups",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-group-membership-mapper",
        "config": {
            "full.path": "false",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "claim.name": "groups",
            "userinfo.token.claim": "true"
        }
    }'

    if [[ -n "$existing_mapper_id" ]]; then
        local updated_json
        updated_json=$(echo "$mapper_json" | python3 -c "import sys,json; d=json.load(sys.stdin); d['id']='$existing_mapper_id'; print(json.dumps(d))")
        local status
        status=$(api_call_status PUT "$ADMIN_API/clients/$client_uuid/protocol-mappers/models/$existing_mapper_id" \
            -d "$updated_json")
        if [[ "$status" == "204" || "$DRY_RUN" == "true" ]]; then
            ok "Group mapper 'groups' updated on client '$CLIENT_ID_NAME'"
        else
            err "Failed to update group mapper (HTTP $status)"
        fi
    else
        local status
        status=$(api_call_status POST "$ADMIN_API/clients/$client_uuid/protocol-mappers/models" \
            -d "$mapper_json")
        if [[ "$status" == "201" || "$DRY_RUN" == "true" ]]; then
            ok "Group mapper 'groups' created on client '$CLIENT_ID_NAME'"
        else
            err "Failed to create group mapper (HTTP $status)"
        fi
    fi
}

# ============================================================
# Step 6: Verification
# ============================================================
verify_all() {
    echo ""
    echo "============================================================"
    log "Verifying configuration..."
    echo "============================================================"

    local failures=0

    # 1. IdP exists and is enabled
    local idp_json
    idp_json=$(api_call GET "$ADMIN_API/identity-provider/instances/$IDP_ALIAS" 2>/dev/null || echo "{}")
    local idp_enabled
    idp_enabled=$(echo "$idp_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('enabled',''))" 2>/dev/null || true)
    if [[ "$idp_enabled" == "True" || "$idp_enabled" == "true" ]]; then
        ok "IdP '$IDP_ALIAS' exists and is enabled"
        local redirect_uri
        redirect_uri=$(echo "$idp_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('config',{}).get('redirectUri', d.get('redirectUrl','')))" 2>/dev/null || true)
        if [[ -n "$redirect_uri" ]]; then
            echo "    Redirect URI: $redirect_uri"
        fi
    else
        err "IdP '$IDP_ALIAS' NOT found or disabled"
        ((failures++))
    fi

    # 2. IdP mappers
    local mapper_count
    mapper_count=$(api_call GET "$ADMIN_API/identity-provider/instances/$IDP_ALIAS/mappers" 2>/dev/null \
        | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [[ "$mapper_count" -ge 3 ]]; then
        ok "IdP has $mapper_count attribute mappers (first-name, email, username)"
    elif [[ "$mapper_count" -gt 0 ]]; then
        warn "IdP has $mapper_count mappers (recommended: 3 — first-name, email, username)"
    else
        warn "IdP has no mappers (profile auto-import won't work — run without --verify-only to create them)"
    fi

    # 3. VERIFY_PROFILE disabled
    local vp_status
    vp_status=$(api_call GET "$ADMIN_API/authentication/required-actions" 2>/dev/null \
        | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    if a['alias'] == 'VERIFY_PROFILE':
        print('enabled' if a.get('enabled') else 'disabled')
        break
else:
    print('not_found')
" 2>/dev/null || echo "error")
    if [[ "$vp_status" == "disabled" || "$vp_status" == "not_found" ]]; then
        ok "VERIFY_PROFILE is disabled"
    else
        err "VERIFY_PROFILE is still enabled"
        ((failures++))
    fi

    # 4. Group exists
    local group_found
    group_found=$(api_call GET "$ADMIN_API/groups?search=$GROUP_NAME&exact=true" 2>/dev/null \
        | python3 -c "
import sys, json
gs = json.load(sys.stdin)
for g in gs:
    if g['name'] == '$GROUP_NAME':
        print('yes')
        break
else:
    print('no')
" 2>/dev/null || echo "error")
    if [[ "$group_found" == "yes" ]]; then
        ok "Group '$GROUP_NAME' exists"
    else
        err "Group '$GROUP_NAME' NOT found"
        ((failures++))
    fi

    # 5. Group membership mapper on client
    local client_uuid
    client_uuid=$(api_call GET "$ADMIN_API/clients?clientId=$CLIENT_ID_NAME" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || true)

    if [[ -n "$client_uuid" ]]; then
        local groups_mapper
        groups_mapper=$(api_call GET "$ADMIN_API/clients/$client_uuid/protocol-mappers/models" 2>/dev/null \
            | python3 -c "
import sys, json
for m in json.load(sys.stdin):
    if m['name'] == 'groups' and m.get('protocolMapper') == 'oidc-group-membership-mapper':
        print('yes')
        break
else:
    print('no')
" 2>/dev/null || echo "error")
        if [[ "$groups_mapper" == "yes" ]]; then
            ok "Group membership mapper exists on client '$CLIENT_ID_NAME'"
        else
            err "Group membership mapper NOT found on client '$CLIENT_ID_NAME'"
            ((failures++))
        fi
    else
        err "Client '$CLIENT_ID_NAME' not found"
        ((failures++))
    fi

    # 6. Keycloak realm OIDC discovery
    local discovery_status
    discovery_status=$(curl -s -o /dev/null -w "%{http_code}" "$KEYCLOAK_URL/realms/$REALM/.well-known/openid-configuration")
    if [[ "$discovery_status" == "200" ]]; then
        ok "OIDC discovery endpoint accessible ($KEYCLOAK_URL/realms/$REALM)"
    else
        err "OIDC discovery endpoint returned HTTP $discovery_status"
        ((failures++))
    fi

    echo ""
    if [[ "$failures" -eq 0 ]]; then
        echo "============================================================"
        ok "All checks passed! GitHub login is configured."
        echo "============================================================"
        echo ""
        echo "  GitHub OAuth callback URL:"
        echo "    $KEYCLOAK_URL/realms/$REALM/broker/$IDP_ALIAS/endpoint"
        echo ""
        echo "  Test login:"
        echo "    Browser: $KEYCLOAK_URL/realms/$REALM/account"
        echo "    CLI:     kosh gateway login  (click 'GitHub' on login page)"
        echo ""
    else
        echo "============================================================"
        err "$failures check(s) failed. Review errors above."
        echo "============================================================"
        return 1
    fi
}

# ============================================================
# Main
# ============================================================
echo ""
echo "============================================================"
echo "  Keycloak GitHub IdP Setup for OpenShell"
echo "  Realm: $REALM | IdP: $IDP_ALIAS | Group: $GROUP_NAME"
echo "============================================================"
echo ""

if [[ "$VERIFY_ONLY" == "true" ]]; then
    verify_all
    exit $?
fi

setup_idp
setup_mappers
disable_verify_profile
setup_group
setup_group_mapper
verify_all
