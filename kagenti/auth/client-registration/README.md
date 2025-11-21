# `client-registration`

`client-registration` is the image that enables Kagenti to automatically register a client (agent or tool) in Keycloak.

## Identity Provider Support

The client registration process supports multiple workload identity providers:

- **SPIRE/SPIFFE** (default): Uses SPIFFE ID from `/opt/jwt_svid.token`
- **Kubernetes ServiceAccount**: Uses ServiceAccount token from `/var/run/secrets/kubernetes.io/serviceaccount/token`

The provider must be explicitly set via the `KAGENTI_IDENTITY_PROVIDER` environment variable (`spire` or `serviceaccount`).

For more details, see the [Identity Providers documentation](../../../docs/identity-providers.md).

# Local development

### Build the image

```sh
cd kagenti/auth/client-registration
docker build -t client-registration .
docker tag client-registration ghcr.io/kagenti/kagenti/client-registration:latest
```

### Install Kagenti

```sh
cd kagenti/installer
uv run kagenti-installer
```

### Load the image into the cluster

```sh
kind load docker-image ghcr.io/kagenti/kagenti/client-registration:latest --name agent-platform
```

### Import a new agent

Open the Agent Platform Demo Dashboard at [http://kagenti-ui.localtest.me:8080](http://kagenti-ui.localtest.me:8080).

Go to the `Import New Agent` tab on the sidebar.

Select the one of the enabled namespaces - e.g. `team1`.

Select the `a2a/weather-service`.

Select `Build Agent`.

### Verify client registration

Open Keycloak at [http://keycloak.localtest.me:8080](http://keycloak.localtest.me:8080).

The default username and password are `admin`.

Go to `Clients` tab on the sidebar.

After a while, a new client should appear.
