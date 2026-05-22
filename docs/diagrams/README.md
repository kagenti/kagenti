# Kagenti Identity & Authentication Flow Diagrams

This directory contains Mermaid sequence diagrams that illustrate the authentication and authorization flows in Kagenti's zero-trust identity architecture.

## Diagrams Overview

### 1. User Authentication Flow
**File**: `01-user-authentication-flow.mmd`
**Description**: Shows how users authenticate with Kagenti UI through Keycloak OIDC flow.

**Key Steps**:
- User accesses Kagenti UI
- UI redirects to Keycloak for authentication
- User provides credentials to Keycloak
- Keycloak returns JWT token to UI
- User gains access to authenticated interface

### 2. Keycloak Client Registration Flow (Secret-based)
**File**: `02-keycloak-client-registration-flow.mmd`
**Description**: Shows how Keycloak client registration uses SPIFFE identity to register and obtain a client secret for application authentication.

**Key Steps**:
- spiffe-helper requests SVID from SPIRE
- SPIRE returns SVID to spiffe-helper
- Keycloak client registration requests SVID from spiffe-helper
- spiffe-helper returns SVID to Keycloak client registration
- Keycloak client registration registers client using SVID credentials with Keycloak
- Keycloak returns application client secret to Keycloak client registration
- AuthBridge reads application client secret for downstream authentication

### 3. Keycloak Client Registration Flow (Secretless with OIDC DCR)
**File**: `03-keycloak-client-registration-dcr-flow.mmd`
**Description**: Illustrates dynamic client registration using OIDC endpoint verification and secretless authentication, eliminating the need for client secrets.

**Key Steps**:
- spiffe-helper requests SVID from SPIRE
- SPIRE returns SVID to spiffe-helper
- Keycloak client registration requests SVID from spiffe-helper
- spiffe-helper returns SVID to Keycloak client registration
- Keycloak client registration sends SVID and OIDC endpoint to Keycloak to enable Dynamic Client Registration
- Keycloak verifies OIDC endpoint and confirms DCR capability
- OIDC endpoint responds that DCR is enabled
- AuthBridge attempts to register with Keycloak using signed metadata or mTLS
- Keycloak verifies AuthBridge identity via OIDC endpoint
- OIDC endpoint confirms AuthBridge identity
- No client secret is returned to Keycloak client registration
- AuthBridge does not need to read any client secret

### 4. Agent Token Exchange Flow
**File**: `04-agent-token-exchange-flow.mmd`
**Description**: Demonstrates OAuth2 token exchange between agents and Keycloak using SPIFFE identity.

**Key Steps**:
- UI forwards user request and token to agent
- Agent retrieves JWT SVID from SPIRE
- Agent performs token exchange with Keycloak
- Keycloak validates SPIFFE identity with SPIRE
- Agent receives scoped token for processing

### 5. Tool Access with Delegated Token Flow
**File**: `05-tool-access-delegated-token-flow.mmd`
**Description**: Shows how agents call tools using delegated tokens with proper permission validation.

**Key Steps**:
- Agent calls tool with delegated token
- Tool validates token with Keycloak
- Tool makes external API calls with validated permissions
- Tool returns processed results to agent

### 6. MCP Gateway Authentication Flow
**File**: `06-mcp-gateway-authentication-flow.mmd`
**Description**: Illustrates authentication flow through the MCP Gateway proxy for Model Context Protocol communications.

**Key Steps**:
- Agent sends MCP request with JWT token to gateway
- Gateway validates token with Keycloak
- Gateway checks tool permissions
- Gateway forwards authenticated request to tool
- Gateway returns MCP response to agent

### 7. Tool Access for external API
**File**: `07-tool-with-external-api-flow.mmd`
**Description**: Shows how agents call internal tools using delegated tokens with proper permission validation, and how Vault exchanges this token for an external API key to securely access external APIs.

**Key Steps**:
- Agent calls tool with delegated token
- Tool validates token with Keycloak
- Keycloak confirms token validity and scopes
- Tool requests external API key from Vault, passing the token
- Vault requests OIDC discovery from Keycloak
- Keycloak returns public keys for token validation
- Vault verifies token claims and enforces Vault policies
- Vault returns external API key to tool
- Tool calls external API using the retrieved API key
- External API returns data to tool
- Tool returns processed data to agent

## Generating Images

### Option 1: Online Editor
1. Visit [mermaid.live](https://mermaid.live)
2. Copy content from any `.mmd` file
3. Click "Actions" → "PNG" or "SVG" to download

### Option 2: Command Line
```bash
# Install mermaid-cli
npm install -g @mermaid-js/mermaid-cli

# Generate all diagrams as PNG
mmdc -i 01-user-authentication-flow.mmd -o 01-user-authentication-flow.png
mmdc -i 02-agent-token-exchange-flow.mmd -o 02-agent-token-exchange-flow.png
mmdc -i 03-tool-access-delegated-token-flow.mmd -o 03-tool-access-delegated-token-flow.png
mmdc -i 04-mcp-gateway-authentication-flow.mmd -o 04-mcp-gateway-authentication-flow.png
mmdc -i 05-tool-with-external-api-flow.mmd -o 05-tool-with-external-api-flow.png

# Generate all diagrams as SVG (vector format)
mmdc -i 01-user-authentication-flow.mmd -o 01-user-authentication-flow.svg
mmdc -i 02-agent-token-exchange-flow.mmd -o 02-agent-token-exchange-flow.svg
mmdc -i 03-tool-access-delegated-token-flow.mmd -o 03-tool-access-delegated-token-flow.svg
mmdc -i 04-mcp-gateway-authentication-flow.mmd -o 04-mcp-gateway-authentication-flow.svg
mmdc -i 05-tool-with-external-api-flow.mmd -o 05-tool-with-external-api-flow.svg
```

### Option 3: Batch Script
```bash
#!/bin/bash
# generate-diagrams.sh

echo "Generating Mermaid diagrams..."

for mmd_file in *.mmd; do
    if [ -f "$mmd_file" ]; then
        base_name="${mmd_file%.mmd}"
        echo "Processing: $mmd_file"

        # Generate PNG
        mmdc -i "$mmd_file" -o "${base_name}.png"

        # Generate SVG
        mmdc -i "$mmd_file" -o "${base_name}.svg"

        echo "✅ Generated: ${base_name}.png and ${base_name}.svg"
    fi
done

echo "🎉 All diagrams generated successfully!"
```

## Integration with Documentation

These diagrams are referenced in the main documentation:
- **[Identity Guide](../identity-guide.md)** - Complete authentication guide with embedded diagrams
- **[Token Exchange Examples](../../kagenti/examples/identity/token_exchange.md)** - Detailed implementation examples

## Related Documentation
- **[Personas and Roles](../../PERSONAS_AND_ROLES.md)** - Developer, operator, and end user personas
- **[Kagenti Identity PDF](../2025-10.Kagenti-Identity.pdf)** - High-level architectural concepts
