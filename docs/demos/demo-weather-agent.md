# Weather Agent Demo

> **This demo has moved.** The Weather Agent demo is now maintained in
> [kagenti-extensions](https://github.com/kagenti/kagenti-extensions) with
> AuthBridge integration for zero-trust security.

## New Location

**[Weather Agent Demo with AuthBridge](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/weather-agent/demo-ui.md)**
— Deploy the Weather Agent via the Kagenti UI with automatic SPIFFE identity
registration and inbound JWT validation.

This is the recommended **getting-started** demo for new users.

## Why It Moved

The original demo in this file used an older version of the Kagenti UI and did
not include AuthBridge security features. The new demo in `kagenti-extensions`:

- Uses the **current Kagenti UI** (Import Agent / Import Tool workflow)
- Adds **AuthBridge inbound JWT validation** — requests are validated before
  reaching the agent
- Adds **automatic identity registration** — the agent registers with Keycloak
  using its SPIFFE ID, with no hardcoded secrets
- Includes **CLI testing steps** for verifying the security flow
- Includes **troubleshooting** and **cleanup** sections

## All Available Demos

See the [AuthBridge Demos Index](https://github.com/kagenti/kagenti-extensions/blob/main/authbridge/demos/README.md)
for a complete list of demos with a recommended learning path.
