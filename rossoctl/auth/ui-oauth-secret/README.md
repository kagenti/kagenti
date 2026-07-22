# `ui-oauth-secret`

`ui-oauth-secret` is the image that creates a Keycloak client for Rossoctl, gets the client secret, then creates a Kubernetes secret name `ui-oauth-secret` that contains the client secret.

This `ui-oauth-secret` secret is then read by the `rossoctl-ui`, which allows the UI to talk to Keycloak.