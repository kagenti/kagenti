# OPA Migration Guide for Kagenti (Kind)

> **Pre-release:** This document shows how OPA can be experimented with prior to its release as part of the Kagenti system. On release, this document should be updated accordingly.

Configures a local Kind-based Kagenti installation to use OPA for policy-based
authorization in AuthBridge.

Install an agent and a tool and test them to work before you start. Then follow these steps to install OPA.
See the annex for how to add rego under this minimal OPA configuration.
If you wish to follow the annex for testing, install the weather agent, the
weather tool and the github issue tool. Also configure two users in the
`kagenti` realm for the demo: `alice` with password `alice` and `bob` with
password `bob` (the annex's helper assumes password == username).

## Architecture

OPA is added as a plugin in both AuthBridge pipelines:

```
Inbound:  jwt-validation → OPA → agent
Outbound: agent → OPA → external service
```

Policies are distributed via a bundle service at
`http://bundle-service.kagenti-system.svc.cluster.local:8080`.

---

## Prerequisites

**Required repos:**
- `kagenti-operator` — bundle-service source
- `kagenti-extensions` — authbridge-proxy source

**Required tools:** `kubectl`, `helm`, `kind`, `docker`/`podman`

Before migrating to OPA, deploy a working agent and tool and confirm they
function on the cluster (agent responds to a task, tool is reachable). Migrate
only once the baseline is verified, so any issue after migration can be
attributed to the OPA changes rather than a pre-existing setup problem.

---

## Step 1 — Deploy bundle-service

OPA requires `bundle-service` running in `kagenti-system` to serve policy bundles.
The `kagenti-operator` repo ships a script that builds the image, loads it into
Kind, installs the `AuthorizationPolicy` CRD, applies the default global policy
CR, and deploys the service (Deployment, Service, ServiceAccount, RBAC):

```bash
cd <path-to-kagenti-operator>/kagenti-operator
./hack/bundle-service-kind.sh kagenti kagenti-system
# Args: [kind-cluster-name] [namespace] — defaults: kagenti kagenti-system
```

The script is idempotent (`kubectl apply`) and waits for the rollout. Verify:

```bash
kubectl get pods -n kagenti-system -l app=bundle-service   # expect 1/1 Running
```

---

## Step 2 — Build and load authbridge-proxy

```bash
cd <path-to-kagenti-extensions>/authbridge
docker build -t localhost/authbridge:local -f cmd/authbridge-proxy/Dockerfile .
kind load docker-image localhost/authbridge:local --name kagenti
```

---

## Step 3 — Update values.yaml

Edit `charts/kagenti/values.yaml` and replace the `pipeline:` block with:

```yaml
  pipeline: |
    inbound:
      plugins:
        - name: jwt-validation
          config:
            issuer: "http://keycloak.localtest.me:8080/realms/kagenti"
            keycloak_url: "http://keycloak-service.keycloak.svc:8080"
            keycloak_realm: "kagenti"
        - name: opa
          config:
            bundle_url: "http://bundle-service.kagenti-system.svc.cluster.local:8080"
    outbound:
      plugins:
        - name: opa
          config:
            bundle_url: "http://bundle-service.kagenti-system.svc.cluster.local:8080"
```

> **token-exchange is intentionally omitted.** This guide covers OPA
> authorization only. The stock pipeline ships a `token-exchange` outbound
> plugin, but with `default_policy: passthrough` and no `routes:` it never
> performs an exchange — it forwards every request untouched — so it is not
> needed to demonstrate OPA. Add it back if you later want per-destination
> token exchange.

---

## Step 4 — Helm upgrade

```bash
helm upgrade kagenti charts/kagenti -n kagenti-system \
    -f charts/kagenti/values.yaml \
    --set openshift=false \
    --set featureFlags.agentSandbox=true \
    --set kagenti-operator-chart.defaults.images.authbridge=localhost/authbridge:local
```

---

## Step 5 — Restart authbridge pods

AuthBridge runs as a sidecar injected into agent workloads, which carry the
`kagenti.io/type=agent` label. Delete the pods to re-inject the sidecar with
the new config:

```bash
kubectl delete pods -n team1 -l kagenti.io/type=agent
```

---

## Verification

**1. OPA plugin present in the authbridge config** (expect it to appear
**twice** — once for the inbound leg and once for the outbound leg):

```bash
kubectl get configmap -n team1 authbridge-runtime-config -o yaml | grep -A 2 'name: opa'
```

Expected:

```
          - name: opa
            config:
              bundle_url: "http://bundle-service.kagenti-system.svc.cluster.local:8080"
--
          - name: opa
            config:
              bundle_url: "http://bundle-service.kagenti-system.svc.cluster.local:8080"
```

**2. Pods running** — each agent pod is `2/2` (agent + `authbridge-proxy`
sidecar) and each tool pod is `1/1`:

```bash
kubectl get pods -n team1
```

Expected (build/run pods may also be listed as `Completed`):

```
NAME                            READY   STATUS    RESTARTS   AGE
weather-service                 2/2     Running   0          ...
weather-tool-...                1/1     Running   0          ...
```

**3. Authbridge logs — confirm OPA initialized.** The critical signal is that
the sidecar loaded its policy bundle from `bundle-service`:

```bash
kubectl logs -n team1 -l kagenti.io/type=agent -c authbridge-proxy --tail=50
```

Expected — look for these two lines:

```
... msg="Bundle loaded and activated successfully. Etag updated to \"sha256:...\"." component=opa-sdk name=authz plugin=bundle
... msg="opa: bundle loaded and policy activated" agent_id=spiffe://.../ns/team1/sa/weather-service
```

If you instead see `opa policy engine not initialized` (HTTP 503 on every
request) or `Bundle load failed: ... no such host`, `bundle-service` is not
reachable — recheck Step 1 (it must be running **before** the OPA-enabled pods
start, or restart the agent pods once it is up).

---

## Rollback

Revert `charts/kagenti/values.yaml` to its original pipeline configuration, then:

```bash
helm upgrade kagenti charts/kagenti -n kagenti-system -f charts/kagenti/values.yaml
kubectl delete pods -n team1 -l kagenti.io/type=agent
```


# Annex: Testing OPA policies end-to-end

This annex walks through proving OPA authorization works, using the weather
agent + weather tool (allowed) and an arbitrary external host — `api.github.com`
— which we will block on the outbound leg. It is written for a Kind cluster with
the following already deployed in `team1`, plus the users `alice` and `bob`
present in the `kagenti` realm:

- `weather-service` — the weather agent (we send requests to it and probe from it)
- `weather-tool-mcp` — the weather tool (stays allowed)

> No second agent or tool is required. The outbound rule blocks a generic
> external host (`api.github.com`), which we probe directly from the weather
> agent's container — so there is nothing extra to deploy and no API token to
> configure. Any reachable host works; `api.github.com` is used only because it
> is always available and returns a real HTTP response when allowed.

The example policy demonstrates two rules in a single namespace-scoped CR:

1. **Inbound** — deny user `alice` from reaching agents in `team1`.
2. **Outbound** — deny `team1` agents from reaching the external host
   `api.github.com` (the weather tool and other hosts stay reachable).

> **Why these two rules use different signals.** The OPA plugin exposes only
> `input.identity.{subject, client_id, scopes}` to policy. `subject` is the JWT
> `sub` claim. The **inbound** leg has an identity (jwt-validation ran), so we
> block by `input.identity.subject`. The **outbound** leg is a *fresh* request
> the agent makes — jwt-validation does not run there, so there is **no user
> identity** on outbound. We therefore gate the outbound rule on the destination
> `input.host`.

---

## A.0 — Starting point (what should already work)

Before doing anything in this annex, confirm the infrastructure baseline below.
This is the state after Steps 1–5: OPA is in the pipeline, but **no**
namespace/client policy has been added yet, so the default global policy allows
every authenticated request. If any of these do not hold, fix that first —
otherwise you cannot tell an OPA denial apart from a pre-existing problem.

1. **Pods running.** The agent pod is `2/2 Running` (agent + authbridge-proxy):

   ```bash
   kubectl get pods -n team1 -l kagenti.io/type=agent
   # weather-service   2/2   Running
   ```

2. **OPA is in the pipeline** on both legs:

   ```bash
   kubectl get configmap authbridge-runtime-config -n team1 \
     -o jsonpath='{.data.config\.yaml}' | grep -c 'name: opa'   # expect 2
   ```

3. **bundle-service is up** and serving the default global policy:

   ```bash
   kubectl get pods -n kagenti-system -l app=bundle-service      # 1/1 Running
   kubectl get authorizationpolicy -n kagenti-system             # 'default', scope global
   ```

These three checks are all you can confirm before touching Keycloak. The
end-to-end behavior — that the weather agent answers and reaches its tool — is
exercised by the first requests you send in A.2/A.3, once Keycloak is prepared
in A.1. With no policy applied, everything is allowed:

| Check | When run | Expected |
|-------|----------|----------|
| `alice` → weather agent (inbound) | A.2 | `200` (allowed) |
| `bob` → weather agent (inbound) | A.2 | `200` (allowed) |
| weather agent → weather tool (outbound) | A.3 | reached (tool's own `406`/`400`, not `403`) |
| weather agent → `api.github.com` (outbound) | A.3 | reached (GitHub's own response, not `403`) |

Everything is allowed because the only policy in force is the default global
one. The rest of the annex adds a policy and shows the denials appear.

---

## A.1 — Prepare Keycloak (one time)

Two changes to the `kagenti` public client are needed so we can (a) mint user
tokens directly and (b) let OPA see *which* user is calling.

1. **Enable Direct Access Grants** on the `kagenti` client — allows the
   OAuth2 password grant used below to obtain a token for a user.

2. **Add a `username → sub` protocol mapper** on the `kagenti` client. The
   `kagenti`-realm tokens for `alice`/`bob` ship **without** a `sub` claim, but
   OPA keys the inbound rule on `input.identity.subject` (the `sub` claim). This
   mapper copies the username into `sub`, so `input.identity.subject` becomes
   `"alice"` / `"bob"`.

Using the Keycloak Admin REST API from your shell (run the whole block in one
shell — the later commands reuse the `$AT`, `$CID`, `$KC`, and `$REALM`
variables set here):

```bash
KC=http://keycloak.localtest.me:8080
REALM=kagenti

# Admin token (master realm) from the keycloak-initial-admin secret
AU=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' | base64 -d)
AP=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d)
AT=$(curl -s -X POST "$KC/realms/master/protocol/openid-connect/token" \
       -d client_id=admin-cli -d "username=$AU" -d "password=$AP" -d grant_type=password \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# UUID of the 'kagenti' client
CID=$(curl -s "$KC/admin/realms/$REALM/clients?clientId=kagenti" -H "Authorization: Bearer $AT" \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')

# (1) enable direct access grants
curl -s -X PUT "$KC/admin/realms/$REALM/clients/$CID" \
     -H "Authorization: Bearer $AT" -H "Content-Type: application/json" \
     -d '{"directAccessGrantsEnabled":true}'

# (2) add username -> sub mapper (run once; a repeat POST returns 409 Conflict)
curl -s -X POST "$KC/admin/realms/$REALM/clients/$CID/protocol-mappers/models" \
     -H "Authorization: Bearer $AT" -H "Content-Type: application/json" -d '{
       "name":"username-as-sub","protocol":"openid-connect",
       "protocolMapper":"oidc-usermodel-attribute-mapper",
       "config":{"user.attribute":"username","claim.name":"sub","jsonType.label":"String",
                 "id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}'
```

Verify the token now carries `sub=alice`:

```bash
curl -s -X POST "$KC/realms/$REALM/protocol/openid-connect/token" \
     -d client_id=kagenti -d username=alice -d password=alice -d grant_type=password -d scope=openid \
  | python3 -c 'import sys,json,base64;t=json.load(sys.stdin)["access_token"].split(".")[1];t+="="*(-len(t)%4);print("sub =",json.loads(base64.urlsafe_b64decode(t)).get("sub"))'
# sub = alice
```

> This demo uses password == username (`alice`/`alice`, `bob`/`bob`), which is
> what the `send_as` helper in A.2 assumes. Create the users accordingly.

---

## A.2 — Send a request on behalf of alice / bob

The weather agent is only reachable inside the cluster, so send from a throwaway
pod. This helper mints a user token and posts an A2A `message/send`:

```bash
send_as() {   # usage: send_as alice | send_as bob
  local user="$1"
  local KC=http://keycloak.localtest.me:8080
  local TOK
  TOK=$(curl -s -X POST "$KC/realms/kagenti/protocol/openid-connect/token" \
         -d client_id=kagenti -d "username=$user" -d "password=$user" \
         -d grant_type=password -d scope=openid \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
  kubectl run "send-$user-$RANDOM" --rm -i --restart=Never --image=curlimages/curl:8.10.1 \
    -n team1 --env="TOK=$TOK" -- sh -c \
    'curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 60 \
       -X POST http://weather-service.team1.svc.cluster.local:8080/ \
       -H "Content-Type: application/json" -H "Authorization: Bearer $TOK" \
       -d "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"message/send\",\"params\":{\"message\":{\"role\":\"user\",\"messageId\":\"m1\",\"parts\":[{\"kind\":\"text\",\"text\":\"What is the weather in Rome?\"}]}}}"'
}
```

Baseline (no policy yet — both allowed):

```bash
send_as alice   # HTTP 200
send_as bob     # HTTP 200
```

---

## A.3 — One-liners: confirm the agent can reach both destinations (baseline)

Before applying any policy, verify the weather agent's sidecar lets the agent
container reach both the weather tool and the external host. These `kubectl exec`
one-liners issue the request from **inside** the agent container, so the traffic
passes through the AuthBridge forward-proxy → outbound OPA. A `403` means OPA
blocked it; anything else means the request reached the destination.

```bash
# weather agent -> external host (api.github.com)
kubectl exec weather-service -n team1 -c agent -- python3 -c \
"import urllib.request as u,urllib.error as e
try: print('HTTP', u.urlopen(u.Request('http://api.github.com/'),timeout=10).status)
except e.HTTPError as x: print('HTTP', x.code)"

# weather agent -> weather tool
kubectl exec weather-service -n team1 -c agent -- python3 -c \
"import urllib.request as u,urllib.error as e
try: print('HTTP', u.urlopen(u.Request('http://weather-tool-mcp.team1.svc.cluster.local:9090/mcp',data=b'{}',headers={'Content-Type':'application/json'}),timeout=10).status)
except e.HTTPError as x: print('HTTP', x.code)"
```

Each command prints a single line — `HTTP <code>`. Baseline result: **neither is
`HTTP 403`**. Each returns the *destination's own* status instead — e.g. GitHub's
`HTTP 200`, and the weather tool's `HTTP 406` (or `400`) — confirming the request
reached the destination (OPA allowed it).

> The wrapper catches `HTTPError` so a non-2xx status (like a `403` block or the
> tool's `406`) prints cleanly as `HTTP <code>` instead of raising a traceback.
>
> Use plain `http://` (not `https://`) for the external host so the request is a
> normal proxied GET whose `input.host` OPA can match. An `https://` URL becomes
> a `CONNECT` tunnel with a different host representation.

---

## A.4 — Apply the policy CR

```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AuthorizationPolicy
metadata:
  name: team1-opa-policy
  namespace: team1
spec:
  scope: namespace
  policies:
    # Rule 1 (inbound): block alice from reaching agents in team1
    - path: inbound/request.rego
      content: |
        package authbridge.ns.inbound.request
        import rego.v1

        # Allow everyone except alice. `allow` false -> ns_ok false -> deny (403).
        default allow := false

        allow if input.identity.subject != "alice"

    # Rule 2 (outbound): block team1 agents from reaching api.github.com
    - path: outbound/request.rego
      content: |
        package authbridge.ns.outbound.request
        import rego.v1

        # Outbound has no user identity — gate on the destination host.
        # Deny api.github.com; allow every other host the agent needs
        # (the weather tool, the LLM at api.openai.com, the otel collector).
        #
        # input.host may carry a port, so match on the hostname prefix to cover
        # both "api.github.com" and "api.github.com:80".
        default allow := false

        allow if not is_blocked_host

        is_blocked_host if startswith(input.host, "api.github.com")
```

Apply it (a copy lives at `docs/authbridge/examples/opa-team1-policy.yaml`):

```bash
kubectl apply -f docs/authbridge/examples/opa-team1-policy.yaml
```

`bundle-service` rebuilds the `team1` bundle automatically on the CR change.
Each agent's OPA polls the bundle on its own interval, so allow **~20–30 s** for
the new decision to take effect before testing.

---

## A.5 — Test the inbound rule: bob allowed, alice blocked

```bash
send_as bob     # HTTP 200  — allowed
send_as alice   # HTTP 403  — blocked by OPA
```

A blocked request returns `HTTP 403` with body
`{"error":"policy.forbidden","message":"policy denied","plugin":"opa"}`.

> If `alice` still returns `200` right after applying, the agent's OPA has not
> polled the new bundle yet — wait a few seconds and retry.

---

## A.6 — Test the outbound rule: weather tool still works, api.github.com blocked

Re-run the same two one-liners from A.3. Now the `api.github.com` call is denied
by OPA while the weather tool call still reaches the tool:

```bash
# weather agent -> api.github.com  (now BLOCKED)
kubectl exec weather-service -n team1 -c agent -- python3 -c \
"import urllib.request as u,urllib.error as e
try: print('HTTP', u.urlopen(u.Request('http://api.github.com/'),timeout=10).status)
except e.HTTPError as x: print('HTTP', x.code)"
# -> HTTP 403      (OPA denied)

# weather agent -> weather tool  (still ALLOWED)
kubectl exec weather-service -n team1 -c agent -- python3 -c \
"import urllib.request as u,urllib.error as e
try: print('HTTP', u.urlopen(u.Request('http://weather-tool-mcp.team1.svc.cluster.local:9090/mcp',data=b'{}',headers={'Content-Type':'application/json'}),timeout=10).status)
except e.HTTPError as x: print('HTTP', x.code)"
# -> HTTP 406      (reached tool = allowed)
```

The contrast is the proof: **`HTTP 403` = OPA blocked** the call to
`api.github.com`; the weather tool returns its own `HTTP 406` (or `400`), meaning
the request passed the outbound policy and reached the tool.

> The rule is **namespace-scoped**, so it applies to *every* agent in `team1`.
> To block only a specific agent, use `scope: client` with the CR named after
> that agent's ServiceAccount instead.

---

## A.7 — Clean up

```bash
kubectl delete -f docs/authbridge/examples/opa-team1-policy.yaml
```

This returns `team1` to the default global policy (all authenticated requests
allowed). The Keycloak client changes from A.1 are harmless and can be left in
place for future testing.

> **Scripted equivalents.** The steps in this annex are automated by
> `scripts/test-opa-weather.sh` (inbound, `setup`/`send`/`block-alice`/`verify`)
> and `scripts/test-opa-combined.sh` (`apply`/`verify`/`cleanup` for this
> combined CR).

