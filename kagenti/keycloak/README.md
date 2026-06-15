# Keycloak GitHub Org Member Authenticator

A Keycloak/RHBK authenticator that rejects First Broker Login from the GitHub
Identity Provider when the user is not a **public** member of a configured
GitHub organization.

## Build

```sh
REGISTRY=quay.io/your-username make push
```

## How the Dockerfile Install works

1. Copy the JAR into Keycloak's `providers/` directory.
2. Run `kc.sh build` (RHBK) or restart your Keycloak distribution so the SPI
   is registered.

Note: The `keycloak.version` property in `pom.xml` defaults to `26.0.7`. Set it to
match your Red Hat Build of Keycloak / Keycloak version before building.

## How to install on kind

```bash
kubectl -n keycloak patch keycloak keycloak --type=merge -p '{"spec":{"image":"quay.io/aslomorg/github-org-keycloak:0.1.0-kc26.5.2"}'
kubectl -n keycloak rollout status --watch statefulset/keycloak
```

## How to install on OpenShift

```bash
kubectl -n keycloak patch keycloak keycloak \
    --type=merge \
    -p '{"spec":{"image":"quay.io/aslomorg/github-org-keycloak:0.1.0-kc26.5.2"}'
kubectl -n keycloak rollout status --watch statefulset/keycloak
```

## How to create a GitHub OAuth app

1. Go to https://github.com/settings/developers and create an OAuth App
2. Set the URL to the home page of your instance.  For example, for Kind use http://kagenti-ui.localtest.me:8080/
3. For Kind, set the Authorization Callback URL to http://keycloak.localtest.me:8080/realms/kagenti/broker/github/endpoint .  Use a similar address for a custom instance.
4. Click **Register Application** to get a client ID.  Record that ID.  Ask for a client secret and record it.

## How to configure Keycloak manually

1. In the admin console, **Authentication → Flows**, duplicate the
   "first broker login" flow (e.g. `github-org-gated`) and add a new execution
   selecting **GitHub Org Member Check**. Set requirement to **REQUIRED** and
   place it **before** "Review Profile" so non-members are rejected
   and changes in org status are noticed.
2. (If using this for non-Kagenti) Open the execution's config and set **GitHub organization** to the org slug
   (e.g. `kagenti`).
3. Go to **Identity Providers** and add a **github** provider.
4. Set the Client ID and Client Secret to the values recorded above.
4. set **First Login Flow** to your new flow `github-org-gated`.

## Script to configure Keycloak

**Under Construction**

## How it works

The authenticator reads the GitHub login from the brokered identity context
attached to the auth session, then calls:

```
GET https://api.github.com/orgs/{org}/members/{username}
```

- `204` → public member, login proceeds.
- anything else (`404`, `302`, network error) → access denied (fail-closed).

This endpoint is anonymous for **public** memberships, so no GitHub token or
`read:org` scope is needed. Private memberships will appear as non-members and
be rejected — if you need to gate on private membership, the authenticator
needs to call `/user/orgs` with the user's GitHub access token from the
brokered context.

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `org` | `kagenti` | GitHub organization login (slug) whose public members are allowed. |
