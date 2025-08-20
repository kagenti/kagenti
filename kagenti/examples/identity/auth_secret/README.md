# `auth-secret`

`auth-secret` is the image that creates a Keycloak client for Kagenti, gets the client secret, then creates a Kubernetes secret name `auth` that contains the client secret.

# Kubernetes

### Install Kagenti

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

### Test authentication

Go to [http://kagenti-ui.localtest.me:8080/](http://kagenti-ui.localtest.me:8080/).

The front page should inform you that the user is not logged in.

All other tabs should be hidden and point you back to the home page for login.

After logging in, all other tabs should be available.
