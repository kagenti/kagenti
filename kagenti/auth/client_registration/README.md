# `kagenti-client-registration`

`kagenti-client-registration` is the image that enables Kagenti to automatically register a client (agent or tool) in Keycloak.

# Local development

### Build the image

```sh
cd kagenti/examples/identity/kagenti-client-registration
docker build -t kagenti-client-registration .
```

### Install Kagenti

```sh
cd kagenti/installer
uv run kagenti-installer
```

### Load the image into the cluster

```sh
kind load docker-image kagenti-client-registration --name agent-platform
```

### Import a new agent

Open the Agent Platform Demo Dashboard at [http://kagenti-ui.localtest.me:8080](http://kagenti-ui.localtest.me:8080).

Go to the `Import New Agent` tab on the sidebar.

Select the `kagenti` namespace.

Select the `acp/aco_ollama_researcher`.

Select `Build Agent`.

### Verify client registration

```sh
kubectl port-forward service/keycloak -n keycloak 8081:8080
```

Open Keycloak at [http://localhost:8081](http://localhost:8081).

The default username and password are `admin`.

Go to `Clients` tab on the sidebar.

After a while, a new client `kagenti/acp-ollama-researcher` should appear.

# Publish image

```sh
docker -D build  --no-cache -t ghcr.io/kagenti/kagenti-ui-oauth-secret:latest -f Dockerfile .
docker push ghcr.io/kagenti/kagenti-ui-oauth-secret:latest 
```