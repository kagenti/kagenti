---
description: What can go wrong?
---

# Troubleshooting

## Issues during Rossoctl installation

### Installation reports "exceeded its progress deadline"

Sometimes it can take a long time to pull container images. Try re-running the installer. Use `kubectl get deployments --all-namespaces` to identify failing deployments.

Try re-running the installer. Use `kubectl get deployments --all-namespaces` to identify failing deployments.

### Docker daemon issues when using Colima instead of Docker Desktop

```shell
export DOCKER_HOST="unix://$HOME/.colima/docker.sock"
```

### Blank UI page on macOS after installation
On macOS, if **Privacy and Content Restrictions** are enabled (under  
System Settings → Screen Time → Content & Privacy Restrictions),  
then after the Rossoctl installation completes, opening the UI may display a blank loading page.

To fix, disable these restrictions and restart the UI.

### Using Podman instead of Docker

The install script expects `docker` to be in your runtime path.

A few problem fixes might include:

- create `/usr/local/bin/docker` link to podman:

  ```console
   sudo ln -s /opt/podman/bin/podman /usr/local/bin/docker
   ```

- install `docker-credential-helper`:

   ```console
   brew install docker-credential-helper
   ```

- fix an issue with `insufficient memory to start keycloak`:

   ```console
   podman machine stop
   podman machine set --memory=12288 --cpus=8
   podman machine start
   ```

- clean, fresh Podman start:

   ```console
   podman machine rm -f
   podman machine init
   podman machine set --memory=12288 --cpus=8
   podman machine start
   ```

- clean the cluster, keep the Podman VM as is:

  ```console
  kind delete cluster --name agent-platform
  ```

## Issues deploying components

### Pull Image errors while deploying components

If you see `Init:ErrImagePull` or `Init:ImagePullBackOff` errors while deploying components,
most likely your Github token expired. 

Error text:

```console
 failed to authorize: failed to fetch oauth token: unexpected status from GET request to https://ghcr.io/token?scope=repository%3Arossoctl%2Frossoctl-client-registration%3Apull&service=ghcr.io: 403 Forbidden
```

Check your [personal access token (classic)](https://github.com/settings/personal-access-tokens/).
Make sure to grant scopes `all:repo`, `write:packages`, and `read:packages`.

You may also get "ghcr.io: 403 Forbidden" errors installing Helm charts during Rossoctl installation.  You may have cached credentials that are no longer valid.  The fix is `docker logout ghcr.io`.

## Issues during runtime

### Service stops responding through gateway

It may happens with Keycloak or even the UI.

Restart the following:

```shell
kubectl rollout restart daemonset -n istio-system  ztunnel
kubectl rollout restart -n rossoctl-system deployment http-istio
```

### Need to edit ENV values

If you need to update the values in `charts/rossoctl/.secrets.yaml` file, e.g., `githubToken`,
delete the secret in all your auto-created namespaces, then re-run the installer:

```shell
kubectl get secret --all-namespaces
kubectl -n my-namespace delete github-token-secret
scripts/kind/setup-rossoctl.sh
```

### Agent log shows communication errors

Rossoctl UI shows Connection errors:

```console
An unexpected error occurred during A2A chat streaming: HTTP Error 503: Network communication error: peer closed connection without sending complete message body (incomplete chunked read)
```

Agent log shows errors:

```console
rossoctl$ kubectl -n teams logs -f weather-service-7f984f478d-4jzv9
.
.
ERROR:    Exception in ASGI application
  + Exception Group Traceback (most recent call last):
  |   File "/app/.venv/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 403, in run_asgi
  |     result = await app(  # type: ignore[func-returns-value]
  |              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  | ..
  +-+---------------- 1 ----------------
    | urllib3.exceptions.ProtocolError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))
```

Most likely the A2A protocol is failing because *ollama* service is not installed or running.

Start *ollama* service in the terminal and keep it running:

```console
ollama serve
```

Then try the prompt again.

### Keycloak stops working

Keycloak stops working and logs show [connection errors](https://github.com/rossoctl/rossoctl/issues/115).

At this time there is no reliable sequence of bringing down and up again
postgres and keycloak. The only reliable approach found so far is either to destroy and re-install
the cluster or delete and re-install keycloak as follows:

```shell
# Delete and re-apply keycloak resources
helm uninstall keycloak -n keycloak
scripts/kind/setup-rossoctl.sh

# Restart related services
kubectl rollout restart daemonset -n istio-system ztunnel
kubectl rollout restart -n rossoctl-system deployment http-istio
kubectl rollout restart -n rossoctl-system deployment rossoctl-ui
```

Deployed agents may need to be restarted to update the Keycloak client.

```shell
kubectl rollout restart -n <agent-namespace> deployment <agent-deployment e.g. weather-service>
```

### Cert-Manager Webhook Errors

When running the rossoctl helm chart upgrade, you may encounter an error stating `failed calling webhook "webhook.cert-manager.io" because the x509 certificate has expired.` This occurs when the internal certificates used by cert-manager to communicate with the Kubernetes API server are no longer valid, preventing the validation of resources like Certificates and Issuers.

To resolve this, you must force cert-manager to regenerate its internal CA and certificates by following these steps:

Delete the expired webhook secret:

```shell
kubectl delete secret cert-manager-webhook-ca -n cert-manager
```

Restart the cert-manager deployments to trigger the issuance of new certificates:

```shell
kubectl rollout restart deployment cert-manager -n cert-manager
kubectl rollout restart deployment cert-manager-webhook -n cert-manager
kubectl rollout restart deployment cert-manager-cainjector -n cert-manager
```

Verify the pods are healthy before retrying your Helm command:

```shell
kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=cert-manager -n cert-manager --timeout=60s
```

Once the pods are back in a Running state with valid certificates, your `helm upgrade --install` 
command should complete successfully.