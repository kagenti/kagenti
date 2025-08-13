# Local

### Start Keycloak

```sh
docker run -p 127.0.0.1:8080:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin quay.io/keycloak/keycloak:26.3.2 start-dev
```

### Create `kagenti` client in Keycloak

Go to Keycloak at [http://keycloak.localtest.me:8080](http://keycloak.localtest.me:8080).

Login with username `admin` and password `admin`.

Create a new client 
  * General settings
    * Set Client ID to `kagenti`
  * Capatibility confg
    * Enable Client Authentication
  * Login settings
    * Set Root URL to `http://localhost:8502`

After creating the client, go to Credentials tab and get the client secret.

### Run Streamlit

```sh
cd kagenti/ui
CLIENT_ID="kagenti" CLIENT_SECRET=<client secret> AUTH_ENDPOINT="http://localhost:8080/realms/master/protocol/openid-connect/auth" TOKEN_ENDPOINT="http://localhost:8080/realms/master/protocol/openid-connect/token" REDIRECT_URI="http://localhost:8502/oauth2/callback" SCOPE="openid profile email" streamlit run Home.py
```

### Test authentication

Go to [http://localhost:8502/](http://localhost:8502/).

The front page should inform you that the user is not logged in.

All other tabs should be hidden and point you back to the home page for login.

After logging in, all other tabs should be available.

# Kubernetes

### Install Kagenti

```sh
cd kagenti/installer
uv run kagenti-installer
```

The installer will fail because `kagenti-ui` requires a secret which is not in the cluster yet.

```
╭───────────────╮
│ Installing Ui │
╰───────────────╯
[15:41:13] ✓ Installing Kagenti UI done.                                              utils.py:88
           ✓ Sharing gateway access for UI done.                                      utils.py:88
           ✗ Waiting for kagenti-ui rollout failed.                                   utils.py:93
           Error: error: deployment "kagenti-ui" exceeded its progress deadline       utils.py:96

Installation aborted.
```

### Create `kagenti` client in Keycloak

Go to Keycloak at [http://keycloak.localtest.me:8080](http://keycloak.localtest.me:8080).

Login with username `admin` and password `admin`.

Create a new client 
  * General settings
    * Set Client ID to `kagenti`
  * Capatibility confg
    * Enable Client Authentication
  * Login settings
    * Set Root URL to `http://kagenti-ui.localtest.me:8080/`

After creating the client, go to Credentials tab and get the client secret.

### Create `auth` K8s secret

This secret is used by 

```sh
kubectl create secret generic auth \
  --namespace kagenti-system \
  --from-literal=ENABLE_AUTH=true \
  --from-literal=CLIENT_ID="kagenti" \
  --from-literal=CLIENT_SECRET=<client secret> \
  --from-literal=AUTH_ENDPOINT="http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/auth" \
  --from-literal=TOKEN_ENDPOINT="http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
  --from-literal=REDIRECT_URI="http://kagenti-ui.localtest.me:8080/oauth2/callback" \
  --from-literal=SCOPE="openid profile email"
```

### Run installer again

```sh
cd kagenti/installer
uv run kagenti-installer
```

### Change the `kagenti-ui` image

Build the `ui-auth` image.

```sh
cd ui
uv lock
docker build -t ui-auth .
```

Inject the `ui-auth` image into kind cluster.

```sh
kind load docker-image ui-auth --name agent-platform
```

Change `kagenti-ui` deployment so it uses `ui-auth` image.

```sh
kubectl set image deployment/kagenti-ui \
  kagenti-ui-container=ui-auth \
  -n kagenti-system
```

