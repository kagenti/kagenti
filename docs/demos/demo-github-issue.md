# GitHub Issue Demo

> **This demo has moved.** The GitHub Issue Agent demo is now maintained in
> [kagenti-extensions](https://github.com/kagenti/kagenti-extensions) with
> AuthBridge integration for zero-trust security.

## New Location

Choose your deployment method:

| Guide | Description |
|-------|-------------|
| **[UI Deployment](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/github-issue/demo-ui.md)** | Import agent and tool via the Kagenti dashboard |
| **[Manual Deployment](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/github-issue/demo-manual.md)** | Deploy everything via `kubectl` and YAML manifests |

## Why It Moved

The original demo in this file used an older version of the Kagenti UI and did
not include AuthBridge security features. The new demos in `kagenti-extensions`:

- Use the **current Kagenti UI** (Import Agent / Import Tool workflow)
- Add **AuthBridge inbound JWT validation** — requests are validated (signature,
  issuer, audience) before reaching the agent
- Add **outbound token exchange** (RFC 8693) — when the agent calls the GitHub
  tool, AuthBridge automatically exchanges the token for one scoped to the tool
- Add **scope-based access control** — Alice (public repos) vs Bob (all repos)
- Add **automatic identity registration** via SPIFFE/SPIRE
- Include comprehensive **CLI testing**, **troubleshooting**, and **cleanup** sections

### Required GitHub PAT Tokens

The new demo still requires two GitHub Personal Access Tokens. Follow
[GitHub's instructions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token)
to create fine-grained PAT tokens:

- **`<PUBLIC_ACCESS_PAT>`** — select **Public Repositories (read-only)** access
- **`<PRIVILEGED_ACCESS_PAT>`** — select **All Repositories** access

## All Available Demos

See the [AuthBridge Demos Index](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md)
for a complete list of demos with a recommended learning path.
