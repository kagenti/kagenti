# kubectl-kagenti

`kubectl` / `oc` plugin for the [Kagenti](https://github.com/kagenti/kagenti) control plane.

**Monorepo path:** `kagenti/kubectl-kagenti/` (Go module `github.com/kagenti/kagenti/kagenti/kubectl-kagenti`). Releases may still ship from [akram/kubectl-kagenti](https://github.com/akram/kubectl-kagenti).

Tracks **RHAIENG-3805** (foundation): Krew layout, global flags, config, `auth status`, stub `login`/`logout`.

## Commands

| Command | Description |
|--------|-------------|
| `kubectl kagenti` | Help (command tree) |
| `kubectl kagenti auth login` | Browser OAuth (Keycloak) + PKCE; saves token |
| `kubectl kagenti auth status` | `GET /api/v1/auth/me` (use `--login` if no token) |
| `kubectl kagenti auth logout` | Deletes token file |
| `kubectl kagenti version` | Version / git commit |

### Global flags (persistent)

- `-n` / `--namespace` — reserved for future resource scope
- `-A` / `--all-namespaces` — reserved for future use
- `-o` / `--output` — `json`, `yaml`, or `wide` (e.g. `kubectl kagenti auth status -o json`)

## Configuration

| Source | Purpose |
|--------|---------|
| `~/.config/kagenti/config.yaml` | Optional `backend_url`, `backend_discovery`, `backend_namespace`, `token_path` |
| `KAGENTI_BACKEND_URL` | Explicit API base URL (highest precedence) |
| `KAGENTI_BACKEND_DISCOVERY` | `auto` (default) \| `route` \| `service` |
| `KAGENTI_BACKEND_NAMESPACE` | Namespace for route/service lookup (default `kagenti-system`) |
| `KAGENTI_KUBECTL` | Path to `kubectl` or `oc` (for discovery) |
| `KAGENTI_TOKEN` / `KAGENTI_TOKEN_PATH` | JWT |

### Default backend URL (no `backend_url` / `KAGENTI_BACKEND_URL`)

Uses your **current kube context** (same as `kubectl` / `oc`):

1. **Route** `kagenti-api` in `kagenti-system` → `https://<route-host>` (OpenShift).
2. If the Route API is missing or the route has no host → **Service** `kagenti-backend` →  
   `http://kagenti-backend.<namespace>.svc.cluster.local:8000`  
   (reachable from **inside the cluster** or wherever cluster DNS resolves; from your laptop you usually want the route or `KAGENTI_BACKEND_URL` / port-forward.)

**Force the service URL** (skip the route even if it exists):

```yaml
# ~/.config/kagenti/config.yaml
backend_discovery: service
```

or:

```bash
export KAGENTI_BACKEND_DISCOVERY=service
kubectl kagenti --backend-discovery=service auth status
```

**Require the route** (fail if not on OpenShift / route missing):

```yaml
backend_discovery: route
```

Example config: [docs/config.example.yaml](docs/config.example.yaml)

Default token file: `~/.config/kagenti/token`.

## Browser login (`auth login`)

1. Resolve **Keycloak** (first match wins):
   - **`keycloak_url`** in config or **`KAGENTI_KEYCLOAK_URL`**
   - ConfigMap **`kagenti-ui-config`** key **`KEYCLOAK_CONSOLE_URL`** (via `kubectl`/`oc`)
   - **`GET /api/v1/auth/config`** on the Kagenti API
   - Secret **`kagenti-ui-oauth-secret`** (`AUTH_ENDPOINT`, `TOKEN_ENDPOINT`, `CLIENT_ID`) if your kube user can read it

2. Open browser → Keycloak → redirect to **`http://127.0.0.1:<port>/oauth/callback`** (default port **8250**).

3. **Keycloak client** (e.g. `kagenti-ui` or `oidc_client_id` in config): enable **Standard flow**, **PKCE** (S256), and add **Valid redirect URI**:

   `http://127.0.0.1:8250/oauth/callback`

   Change port with **`oidc_local_port`** / **`KAGENTI_OIDC_LOCAL_PORT`** and register that URI too.

4. Confidential clients: set **`KAGENTI_OIDC_CLIENT_SECRET`**.

```bash
kubectl kagenti auth login
kubectl kagenti auth status --login   # login if no token, or re-login if token expired (401)
kubectl kagenti auth logout
```

You can still set **`KAGENTI_TOKEN`** or the token file manually.

## Build / install (development)

```bash
make build    # ./kubectl-kagenti
make install  # copies to ~/.local/bin
```

Ensure `kubectl-kagenti` is on `PATH`; then `kubectl kagenti` is discovered automatically.

## OpenShift (`oc kagenti`)

Krew installs `kubectl-kagenti`. For `oc kagenti`, symlink the same binary:

```bash
ln -s "$(command -v kubectl-kagenti)" "$HOME/.local/bin/oc-kagenti"
```

## Krew

1. Tag and release (GoReleaser uploads `kubectl-kagenti_v*_*_*.tar.gz`).
2. Run `./scripts/fill-krew-sha256.sh v0.1.0` and update `sha256` in [deploy/krew/kagenti.yaml](deploy/krew/kagenti.yaml).
3. Install:

   ```bash
   kubectl krew install --manifest-url https://raw.githubusercontent.com/akram/kubectl-kagenti/main/deploy/krew/kagenti.yaml
   ```

For **local** Krew testing without GitHub:

```bash
make krew-pack
# Point one platform entry in deploy/krew/kagenti.yaml to file:///.../dist/kubectl-kagenti_...tar.gz and set sha256 from make output
kubectl krew install --manifest=deploy/krew/kagenti.yaml
```

## Acceptance (RHAIENG-3805)

- [x] Plugin layout + Krew manifest (install after release + SHA update)
- [x] Help shows command tree
- [x] `auth status` with valid JWT against configured backend
- [x] `auth login` / `auth logout`; `auth status --login`

## License

Apache-2.0
