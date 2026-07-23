---
draft: true       # excluded from https://www.rossoctl.dev/
---

# AuthBridge TLS Bridge

The **TLS bridge** lets AuthBridge decrypt an agent's *outbound* HTTPS so the
AuthBridge pipeline (parsers, guardrails, audit) can inspect request and
response payloads instead of seeing an opaque `CONNECT host:443` tunnel.

It works by terminating the agent's outbound TLS at the proxy-sidecar's Go
forward proxy using a per-agent CA, running the decrypted request through the
normal outbound pipeline, then re-originating a verified TLS connection to the
real upstream.

> **This is L7 interception and is OFF by default.** It is opt-in per agent and
> must be deliberately enabled by a platform operator.

## Requirements

- `authBridgeMode` **proxy-sidecar** or **lite** (the bridge lives in the Go
  forward proxy; it is rejected with `envoy-sidecar`).
- **cert-manager** installed (the operator provisions a per-agent CA
  `Certificate`/`Issuer`; cert-manager issues the Secret). cert-manager is
  already installed on standard Kind and OpenShift rossoctl installs.
- A **rossoctl-operator** build that supports the TLS bridge (the feature is
  inert on operator versions that predate it).

It is decoupled from SPIRE/mTLS — the bridge CA comes from cert-manager, not an
SVID.

## Enabling it

There is **no cluster feature gate and no separate UI flag** — the TLS bridge is
a plain per-agent option, exactly like `mtlsMode`. The single control is the
per-agent field, which defaults to disabled:

| Control | Where | Effect |
|---------|-------|--------|
| `spec.tlsBridgeMode: enabled` | per-agent — set by the UI toggle, or directly on the AgentRuntime CR | Opts that one agent into the bridge. Default `disabled`. |

When importing an agent in the UI, check **"Decrypt outbound TLS for inspection
(TLS bridge)"** (shown in proxy-sidecar mode, alongside the mTLS control). It
maps to `AgentRuntime.spec.tlsBridgeMode=enabled`; the operator then provisions
the per-agent CA (via cert-manager) and the sidecar starts bridging. Nothing is
decrypted for agents that don't opt in.

## How to tell it is active

On the agent's detail page, the **AuthBridge** tab shows **TLS bridge: Active**
when the sidecar reports the bridge is on. The agent's outbound HTTPS requests
then appear — decrypted — in the AuthBridge session API (`:9094`).

## Security note

When the bridge is on, the agent's outbound TLS is decrypted and its payloads
(including any `Authorization` headers) flow through the AuthBridge pipeline and
session store. Enable it only where that inspection is intended.
