# Demonstrating Keycloak Token Exchange

## Steps to set up SPIRE

### Step 1.1: Create the Kind Clusters

If a Podman machine is up and running skip the following step. Else on OSX or Windows, run this command to start the podman machine:

```shell
podman machine init -m 4096 --rootful=true
podman machine start
```

If you have multiple container runtimes, specify the proper runtime:

```shell
export KIND_EXPERIMENTAL_PROVIDER=podman
```

Now, we can create the Kind clusters. We will add extra port mappings to cluster A because we will set up ingress on that cluster. 

```shell
kind create cluster --name=cluster --config=resources/cluster/kind_cluster_config.yaml
```

### Step 1.2: Set up Ingress on Cluster A

On Kind, we can deploy an Nginx Ingress controller to access application services running within the environment.

Set the `APP_DOMAIN` environment variable to contain the subdomain for which all applications can be accessed. On RHEL: 

```shell
export APP_DOMAIN=$(ip -4 addr show ens192 | ggrep -oP '(?<=inet\s)\d+(\.\d+){3}').nip.io
```

On MacOS/Windows:

```shell
export APP_DOMAIN=$(ipconfig getifaddr en0).nip.io
```

Confirm the variable has been populated:

```shell
echo $APP_DOMAIN
```

A value similar to `x.xxx.xxx.xxx.nip.io` indicates the variable has been set properly.

Deploy the ingress controller:

```shell
kubectl apply -f resources/cluster/kind_ingress_deployment.yaml --context=kind-cluster
kubectl wait --namespace ingress-nginx --context=kind-cluster \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=90s
```

### Step 1.3: Deploy SPIRE on the Kind cluster

Now, we can deploy SPIRE on the Kind cluster:

```shell
helm upgrade --install -n spire-mgmt spire-crds spire-crds --repo https://spiffe.github.io/helm-charts-hardened/ --create-namespace --kube-context=kind-cluster
envsubst < resources/spire/helm_values.yaml | helm upgrade --install -n spire-mgmt spire spire --repo https://spiffe.github.io/helm-charts-hardened/ -f - --kube-context=kind-cluster
```

Finally, let's create an ingress for HTTP connection to the SPIRE OIDC service:

```shell
envsubst < resources/spire/oidc-ingress-http.yaml | kubectl apply --context=kind-cluster -f -
```

### Step 1.4: Deploy SPIRE-enabled workloads on the cluster

Let's deploy our workloads into the cluster. For this demo, we have a three-tiered architecture:

```
 -------      -------      ------
|  API  | -> | Agent | -> | Tool |
 -------      -------      ------
```

And we will mimic the flow of access tokens from API to Tool. This involves several steps:

1. Simulate user login with API workload. We will use the password grant for demonstration purposes only. This will end in the issuance of a token to the API workload. 
2. Simulate the exchange of the access token for the API to the access token for the Agent. 
3. [todo] Simulate the token exchange of the access token for the Agent to the access token for the Tool. 

So to do this, we will deploy three workloads each in their own namespaces: `api`, `agent`, `tool`. 

```shell
kubectl apply -f resources/spire/workload_api.yaml --context=kind-cluster
kubectl wait -n api --context=kind-cluster --for=condition=ready pod --selector=app=client --timeout=180s
kubectl apply -f resources/spire/workload_agent.yaml --context=kind-cluster
kubectl wait -n agent --context=kind-cluster --for=condition=ready pod --selector=app=client --timeout=180s
```

Once they are running, let's exec into the pod and cat the SVIDs:

```shell
kubectl exec -n api -it $(kubectl get po -n api -o name -l app=client --context=kind-cluster) --context=kind-cluster -- cat /opt/jwt_svid.token
kubectl exec -n agent -it $(kubectl get po -n agent -o name -l app=client --context=kind-cluster) --context=kind-cluster -- cat /opt/jwt_svid.token
```

## Steps to set up Keycloak

Now that we have deployed SPIRE, let's deploy Keycloak!

We are using a custom-built Keycloak image that enables preview features and also modifies the JWT Bearer Client Authentication Profile. If you would like to build and run Keycloak yourself, please see [our docs](./custom_keycloak.md) on how to do so.

```shell
kubectl apply -f resources/keycloak/namespace.yaml
kubectl apply -f resources/keycloak/statefulset.yaml
kubectl apply -f resources/keycloak/service.yaml
envsubst < resources/keycloak/ingress.yaml | kubectl apply -f - 
```

Then, we can access keycloak at the URL printed here: 

```
echo keycloak.$APP_DOMAIN
```

## Keycloak Set up:

### Required values

We require some values from the terminal. Please run the following to print them out and take note of them as we complete Keycloak set up.

```shell
export SPIFFE_ID_API=spiffe://$APP_DOMAIN/ns/api/sa/default
export SPIFFE_ID_AGENT=spiffe://$APP_DOMAIN/ns/agent/sa/default
export JWKS_URL=http://oidc-discovery-http.$APP_DOMAIN/keys
```

We can print them out here:

```shell
echo SPIFFE_ID_API=$SPIFFE_ID_API
echo SPIFFE_ID_AGENT=$SPIFFE_ID_AGENT
echo JWKS_URL=$JWKS_URL
```

### Initial realm set up

Port forward Keycloak
```shell
kubectl port-forward statefulset/keycloak-for-tornjak -n keycloak 8080:8080
```

1. Access Keycloak (admin/admin)
2. Create a new realm `Demo` [this is case-sensitive]
3. Select that realm, go to `Users` on the sidebar, and create a new user. 
4. Once that user is created, set a password by going to `Users > <username> > Credentials` where Credentials is in the top breadcrumbs. Set the password. Keep note of the credentials you used. 

### Set up clients and client scopes

```shell
cd config
```

Create a Python virtual environment
```shell
python -m venv venv
. venv/bin/activate
```

Recreate the `SPIFFE_ID_API`, `SPIFFE_ID_AGENT`, and `JWKS_URL` environment variables.

Install requirements and run script to set up clients and client scopes.
```shell
pip install -r requirements.txt
python demo_keycloak_config.py
```

<!-- ### Set up Client Profile for API workload

We are using SPIRE to authenticate the workload to Keycloak. 

1. In the left sidebar, select `Clients`, then `Create client`
2. We'll name the application the value of `$SPIFFE_ID_API` that you printed in the terminal. **Be sure to paste your own SPIFFE ID**
3. Select `Client authentication` to true, and select Authentication flows `Standard flow` and `Direct access grants`. 
4. Save
5. Now go to `Clients > spiffe://... > Client scopes > spiffe://...-dedicated > Scope` and set `Full scope allowed` to `Off`. 
6. We will now configure client authentication of this application. Go to `Clients > spiffe://... > Credentials`. Under `Client Authenticator` select `Signed Jwt`. Click save. 
7. Now go to `Keys` in the breadcrumbs at the top and turn on `Use JWKS URL`. This opens a new field. We must put the `JWKS_URL` into this field, which you would have printed out earlier. 

### Set up Client Profile for Agent workload

We are using SPIRE to authenticate the workload to Keycloak.

1. In the left sidebar, select `Clients`, then `Create client`
2. We'll name the application the value of `$SPIFFE_ID_AGENT` that you printed in the terminal. **Be sure to paste your own SPIFFE ID**
3. Select `Client authentication` to true, and select Authentication flows `Standard flow` and `Direct access grants`. 
4. Save
5. Now go to `Clients > spiffe://... > Client scopes > spiffe://...-dedicated > Scope` and set `Full scope allowed` to `Off`. 
6. We will now configure client authentication of this application. Go to `Clients > spiffe://... > Credentials`. Under `Client Authenticator` select `Signed Jwt`. Click save. 
7. Now go to `Keys` in the breadcrumbs at the top and turn on `Use JWKS URL`. This opens a new field. We must put the `JWKS_URL` into this field, which you would have printed out earlier. 

### Set up Client Profile for Tool workload

In the case of two workloads, there is no need for token exchange. It is only when a second-tier workload must also call a third workload that token exchange may be necessary. This is because the audience present in the access token of the tier two workload may not be equal to the audience accepted by the third workload. 

Thus, we set up a third client profile for the tool workload. Let us suppose the tool is external and has client id `ExampleTool`, and accepts JWTs issued by this Keycloak instance with audience `ExampleTool`. 

1. In the left sidebar, select `Clients`, then `Create client`
2. We'll name the application `ExampleTool`.
3. Select `Client authentication` to false, and de-select all Authentication flows. 
4. Save
5. Now go to `Clients > ExampleTool > Client scopes > ExampleTool-dedicated > Scope` and set `Full scope allowed` to `Off`. 

### Add proper client scopes

When an application is asking for an access token, we can elect to have optional scopes to customize the received JWT at runtime. The API client needs to be able to obtain a JWT with audience of the Agent client application. The Agent client needs to be able to obtain a JWT with audience of the ExampleTool client application

#### Add client scope to API client for the Agent as an audience

1. Finally, we will create a client scope that allows the client to request a specified audience. In the left-hand side bar, go to `Client scopes`. 
2. Click `Create client scope`. Name the client scope `agent-audience`. Set the type to `Optional` and Protocol to `OpenID Connect`. Click `Save`. 
3. Now that you have saved, you should see a `Mappers` tab near the top. Click on `Mappers > Configure a new mapper > Audience`. 
4. Enter `agent-audience` as the name, and add the agent SPIFFE ID, `$SPIFFE_ID_AGENT`, to the `Included Client Audience` (It should look something like `spiffe://xx.x.xx.xxx.nip.io/ns/agent/sa/default`). Click `Save`. 
5. Finally, let's add the client scope to the API client profile in Keycloak. Go to `Clients > spiffe://.../ns/api/... > Client scopes > Add client scope`. Select `agent-audience`. Add as `Optional`. 

#### Add client scope to Agent client for the ExampleTool as an audience

8. Finally, we will create a client scope that allows the client to request a specified audience. In the left-hand side bar, go to `Client scopes`. 
9. Click `Create client scope`. Name the client scope `tool-audience`. Set the type to `Optional` and Protocol to `OpenID Connect`. Click `Save`. 
10. Now that you have saved, you should see a `Mappers` tab near the top. Click on `Mappers > Configure a new mapper > Audience`. 
11. Enter `tool-audience` as the name, and write a custom string `example-tool` in `Included Custom Audience`. Click `Save`. 
12. Finally, let's add the client scope to the API client profile in Keycloak. Go to `Clients > spiffe://.../ns/agent/... > Client scopes > Add client scope`. Select `tool-audience`. Add as `Optional`.  -->

### Enable Token exchange for Agent Workload to obtain an access token for ExampleTool

Note: These steps come from [this documentation](https://www.keycloak.org/securing-apps/token-exchange#_internal-token-to-internal-token-exchange). 

5. Now go to `Clients > ExampleTool > Client details` and in the breadcrumbs at the top, click on `Permissions`
6. Enable Permissions, and you should see several items under Permission List. We will eventually want to edit the token-exchange permission. Click on it. 
7. Click `Client details` in the breadcrumbs at top of the screen. 
8. Go to `Authorization > Policies` and Create a Policy. We will create a Client policy named `tool-exchange` and list `spiffe://.../ns/agent/...` under Clients. Then hit `Save`.
9. Now that the policy is created, go back to `ExampleTool` to the token-exchange permission and add the policy under the `Policies` field. Hit save. 

## Simulate the access token flows

Now that Keycloak has been set up, we will simulate the flow of access tokens in the scenario where: 

1. A user logs in via the API tier application
2. The API tier application makes a call to the Agent tier application
3. The Agent tier application exchanges the received token for a new token to access the ExampleTool application

### Obtain the initial token that is to be presented to the Agent tier application

First we will curl command to obtain an access token. We will be using the Resource Owner Password Credentials Grant type as an easy way to obtain an access token by using user credentials via CURL. 

In practice, note that this grant is removed from OAuth2.1 and is not recommended at all in real applications because it places much trust on application code to securely handle usernames and passwords. Instead in real applications, please consider [alternatives](https://auth0.com/docs/get-started/authentication-and-authorization-flow/which-oauth-2-0-flow-should-i-use) depending on your application type. We are using this flow merely out of convenience. 


In ther terminal, let's simulate a log in for the application. We will use the Password grant for demo purposes only. First, export the credentials of the user you created in this realm. 

```shell
export USER_NAME=<user name>
export USER_PASSWORD=<password>
```

Now, we will use the application's SPIRE-issued JWT to authenticate to Keycloak. Let's store the JWT in the variable. 

```shell
export SPIFFE_JWT_API=$(kubectl exec -n api -it $(kubectl get po -n api -o name -l app=client --context=kind-cluster) --context=kind-cluster -- cat /opt/jwt_svid.token)
```

If you inspect this token, you should see a payload similar to: 

```json
{
  "aud": [
    "http://localhost:8080/realms/Demo"
  ],
  "exp": 1738...,
  "iat": 1738...,
  "iss": "https://oidc-discovery.xx.x.xx.xxx.nip.io",
  "sub": "spiffe://xx.x.xx.xxx.nip.io/ns/api/sa/default"
}
```

Finally, let's obtain our initial access token with the following CURL command: 

```shell
curl -sX POST -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_assertion=$SPIFFE_JWT_API" \
    -d "grant_type=password" \
    -d "username=$USER_NAME" \
    -d "password=$USER_PASSWORD" \
    -d "scope=agent-audience" \
    -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
    -d "client_id=$SPIFFE_ID_API" \
        "http://localhost:8080/realms/Demo/protocol/openid-connect/token" | jq -r
```

This should return something like the following: 

```json
{
  "access_token":"ey...",
  "expires_in":300,
  "refresh_expires_in":1800,
  "refresh_token":"ey...",
  "token_type":"Bearer",
  "not-before-policy":0,
  "session_state":"6af3bb4d-abdd-40dc-9df5-960328e683cc",
  "scope":"email profile"
}
```

If you inspect the access token at [jwt.io](https://jwt.io), you should see the payload looking like: 

```json
{
  "exp": 173...,
  "iat": 173...,
  "jti": "xxxx-xx-xx-xx-xxxxxx",
  "iss": "http://localhost:8080/realms/Demo",
  "aud": "spiffe://xx.x.xx.xxx.nip.io/ns/agent/sa/default",
  "sub": "xxxx-xx-xx-xx-xxxxxx",
  "typ": "Bearer",
  "azp": "spiffe://xx.x.xx.xxx.nip.io/ns/api/sa/default",
  "sid": "xxxx-xx-xx-xx-xxxxxx",
  "acr": "1",
  "allowed-origins": [
    "/*"
  ],
  "scope": "email profile",
  "email_verified": false,
  "name": "<user's first and last name>",
  "preferred_username": "<username>",
  "given_name": "<user first name>",
  "family_name": "<user last name>",
  "email": "<user email>"
}
```

Notice that the `aud` claim has been specified because we requested the scope to be `agent-audience`. 



### Make the requests

The access token is the key here. If you were to visit [jwt.io](https://jwt.io), and paste the access token in there, you should see the token has `aud` value with the Agent SPIFFEID. Let's store it in an environment variable:

```shell
export ACCESS_TOKEN=$(curl -sX POST -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_assertion=$SPIFFE_JWT_API" \
    -d "grant_type=password" \
    -d "username=$USER_NAME" \
    -d "password=$USER_PASSWORD" \
    -d "scope=agent-audience" \
    -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
    -d "client_id=$SPIFFE_ID_API" \
        "http://localhost:8080/realms/Demo/protocol/openid-connect/token" | jq -r .access_token)
```

Now we can use it in a subsequent call to exchange the token. We now want to simulate the agent workload exchanging the token it received for a new token with `ExampleTool` as its `aud` claim. First let's obtain our SPIRE-issued JWT:

```shell
export SPIFFE_JWT_AGENT=$(kubectl exec -n agent -it $(kubectl get po -n agent -o name -l app=client --context=kind-cluster) --context=kind-cluster -- cat /opt/jwt_svid.token)
```

And finially we can do the token exchange: 

```shell
curl -sX POST -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=$SPIFFE_ID_AGENT" \
    -d "client_assertion=$SPIFFE_JWT_AGENT" \
    -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
    -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
    -d "requested_token_type=urn:ietf:params:oauth:token-type:refresh_token" \
    -d "subject_token=$ACCESS_TOKEN" \
    -d "audience=ExampleTool" \
        "http://localhost:8080/realms/Demo/protocol/openid-connect/token" | jq -r
```

Again the response should look similar to the response above. And again, the key is the access token value. If you were to plug in this access token to [jwt.io](https://jwt.io) you should get a very similar token - but with the `aud` claim now as `ExampleTool`. 
