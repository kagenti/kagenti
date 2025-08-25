# `kagenti-ui-oauth-secret`

`kagenti-ui-oauth-secret` is the image that creates a Keycloak client for Kagenti, gets the client secret, then creates a Kubernetes secret name `kagenti-ui-oauth-secret` that contains the client secret.

This `kagenti-ui-oauth-secret` secret is then read by the `kagenti-ui`, which allows the UI to talk to Keycloak.

# Publish image

```sh
docker -D build  --no-cache -t ghcr.io/kagenti/kagenti-ui-oauth-secret:latest -f Dockerfile .
docker push ghcr.io/kagenti/kagenti-ui-oauth-secret:latest 
```