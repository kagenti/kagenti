# Granting Agent Access to Users

When agents are deployed with AuthBridge, they validate inbound tokens against their own SPIFFE-based identity. For a user to discover and interact with an agent through the demo app, their token must include the agent's SPIFFE ID in the `aud` (audience) claim.

This document covers:
- **System-wide access** — all users can access the agent
- **Per-user access** — only users with a specific role can access the agent

## Background

Each AuthBridge-protected agent has a Keycloak client registered with a SPIFFE-based client ID:

```
spiffe://<domain>/ns/<namespace>/sa/<agent-name>
```

For example:
- `spiffe://localtest.me/ns/team1/sa/git-issue-agent`
- `spiffe://localtest.me/ns/team1/sa/weather-agent`

When the demo app sends a request to an agent on behalf of a user, the agent's AuthBridge sidecar checks that the user's token contains the agent's SPIFFE ID in the `aud` claim. If it doesn't, the request is rejected with 401, and the demo app hides the agent from the user.

## Prerequisites

- The agent is deployed with AuthBridge enabled (`kagenti.io/inject: enabled`)
- The agent's Keycloak client exists (created automatically by the kagenti-operator during agent registration)
- You have admin access to Keycloak

## Automated Setup

The `grant_agent_access.py` script (run by `make grant-agent-access`) configures **system-wide** audience scopes for a predefined set of demo agents. For per-user access control, follow the manual steps below.

---

## System-Wide Access (All Users)

Use this approach when every authenticated user should be able to access the agent.

### Step 1: Create a Client Scope

1. Open Keycloak Admin Console: `http://keycloak.localtest.me:8080/admin`
2. Select the **kagenti** realm
3. Navigate to **Client scopes** → **Create client scope**
4. Fill in:
   - **Name**: `<agent-name>-access` (e.g., `git-issue-agent-access`)
   - **Protocol**: `OpenID Connect`
   - **Include in token scope**: `On`
   - **Display on consent screen**: `Off`
5. Click **Save**

### Step 2: Add an Audience Mapper

1. In the newly created scope, go to the **Mappers** tab
2. Click **Configure a new mapper** → select **Audience**
3. Fill in:
   - **Name**: `<agent-name>-audience` (e.g., `git-issue-agent-audience`)
   - **Included Client Audience**: select the agent's SPIFFE client ID
     (e.g., `spiffe://localtest.me/ns/team1/sa/git-issue-agent`)
   - **Add to access token**: `On`
   - **Add to ID token**: `Off`
   - **Add to token introspection**: `On`
4. Click **Save**

### Step 3: Add the Scope to the Demo App Client as Default

1. Navigate to **Clients** → **app-demo**
2. Go to the **Client scopes** tab
3. Click **Add client scope**
4. Select the scope (e.g., `git-issue-agent-access`)
5. Set **Assigned type** to **Default**
6. Click **Add**

All users of the demo app will now receive this agent's audience in their tokens.

---

## Per-User Access (Role-Based)

Use this approach when only specific users should be able to access an agent. The mechanism: create a realm role for the agent, assign it to authorized users, and configure a **conditional audience mapper** that only adds the agent's SPIFFE ID to tokens of users who have that role.

### Step 1: Create a Realm Role for the Agent

1. Navigate to **Realm roles** → **Create role**
2. Fill in:
   - **Role name**: `<agent-name>-access` (e.g., `git-issue-agent-access`)
   - **Description**: `Access to the git-issue-agent`
3. Click **Save**

### Step 2: Assign the Role to Authorized Users

1. Navigate to **Users** → select a user (e.g., `alice`)
2. Go to the **Role mapping** tab → **Assign role**
3. Filter by realm roles → select `<agent-name>-access` → **Assign**

Repeat for each user who should have access to this agent.

### Step 3: Create a Client Scope

1. Navigate to **Client scopes** → **Create client scope**
2. Fill in:
   - **Name**: `<agent-name>-access` (e.g., `git-issue-agent-access`)
   - **Protocol**: `OpenID Connect`
   - **Include in token scope**: `On`
   - **Display on consent screen**: `Off`
3. Click **Save**

### Step 4: Add a Conditional Audience Mapper

1. In the scope, go to the **Mappers** tab
2. Click **Configure a new mapper** → select **Audience**
3. Fill in:
   - **Name**: `<agent-name>-audience`
   - **Included Client Audience**: select the agent's SPIFFE client ID
     (e.g., `spiffe://localtest.me/ns/team1/sa/git-issue-agent`)
   - **Add to access token**: `On`
   - **Add to ID token**: `Off`
   - **Add to token introspection**: `On`
4. Click **Save**

### Step 5: Add a Role Condition to the Scope

Keycloak evaluates scope role mappings: if a scope has a realm role assigned, the scope's mappers only apply to users who have that role.

1. In the scope, go to the **Scope** tab
2. Click **Assign role**
3. Select the role you created in Step 1 (e.g., `git-issue-agent-access`)
4. Click **Assign**

Now, the audience mapper will only fire for users who have the `git-issue-agent-access` role.

### Step 6: Add the Scope to the Demo App Client as Default

1. Navigate to **Clients** → **app-demo**
2. Go to the **Client scopes** tab
3. Click **Add client scope**
4. Select the scope (e.g., `git-issue-agent-access`)
5. Set **Assigned type** to **Default**
6. Click **Add**

### Result

- **Alice** (has `git-issue-agent-access` role): her token includes the agent's SPIFFE ID → she can see and chat with the agent
- **Bob** (does NOT have the role): his token does NOT include the agent's SPIFFE ID → the agent is hidden from him

---

## User Re-Login

After any scope or role change, users must **log out and log back in** (or wait for token refresh) to receive updated tokens.

## Verifying the Configuration

Decode a user's access token (from browser dev tools → Application → Local Storage) and check the `aud` claim:

**Alice (has access):**
```json
{
  "aud": [
    "http://keycloak.localtest.me:8080/realms/kagenti",
    "spiffe://localtest.me/ns/team1/sa/git-issue-agent"
  ]
}
```

**Bob (no access):**
```json
{
  "aud": "http://keycloak.localtest.me:8080/realms/kagenti"
}
```

## Adding a New Agent

When a new agent is deployed via the Kagenti dashboard's "Import Agent" feature:

1. Wait for the kagenti-operator to register the agent's Keycloak client (automatic)
2. Choose system-wide or per-user access and follow the steps above
3. Users log out and back in

The demo app will then show the new agent only to users whose tokens contain the matching audience.

## Summary of Keycloak Objects

| Object | Name Pattern | Purpose |
|--------|-------------|---------|
| Client | `spiffe://{domain}/ns/{ns}/sa/{agent}` | Agent's identity (created by operator) |
| Client Scope | `{agent-name}-access` | Container for the audience mapper |
| Protocol Mapper | `{agent-name}-audience` | Adds agent's SPIFFE ID to token `aud` |
| Realm Role (per-user only) | `{agent-name}-access` | Gates which users get the audience |
| Scope Role Mapping (per-user only) | role → scope | Makes the mapper conditional on the role |
