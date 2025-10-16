# Identity Demo Aspects

**NOTE:** *This document is work in progress*

This document contains all considerations related to Identity in Agentic Platform.

There are already several documents specific to identity:

* [Kagenti Identity Overview](./2025-10.Kagenti-Identity.pdf)
* [Client Registration](../kagenti/examples/identity/kagenti_client_registration/README.md)
* [Token Exchange](../kagenti/examples/identity/token_exchange.md)

## SPIRE Environment

To verify OIDC service for SPIRE is properly setup:

```shell
curl http://spire-oidc.localtest.me:8080/keys
curl http://spire.localtest.me:8080/.well-known/openid-configuration
```

Check if Tornjak started correctly.

Test the Tornjak API access:

```shell
curl http://spire-tornjak-api.localtest.me:8080/
```

This should return something like:

```console
"Welcome to the Tornjak Backend!"
```

Now test the Tornjak UI access:

```shell
open http://spire-tornjak-ui.localtest.me:8080/
```

Agents and Tools get SPIFFE Id as follow:

```console
spiffe://localhost.me/ns/team/sa/weather-service
spiffe://localhost.me/ns/team/sa/weather-tool
```
