# Token Exchange for Agentic Platform

## Introduction

Dynamic agentic platforms require equally dynamic identity solutions. By combining OAuth2.0,
Token Exchange, and SPIRE, we build secure, scalable systems that adhere to zero-trust
principles without compromising developer velocity.
This approach enables secure, per-request delegation, granular access control, and workload
attestation, all while avoiding the pitfalls of static credentials and over-permissioned systems.

## Simple Use Case

The flow of this use case is following:

1. The Agent Orchestrator deploys an agent.
2. A user initiates a request to the Agent Orchestrator.
3. The Agent Orchestrator redirects the request to an appropriate Agent
4. The Agent needs to access a third-party tool (like an API) on the user’s behalf.

(Picture of a basic agentic flow.)

Proposed architecture that enforces Zero Trust, least privilege, and short-lived credentials through the combination of OAuth2.0, Token Exchange, and SPIFFE/SPIRE workload identity.

These examples assume Keycloak is configured correctly and SPIRE has issued JWT-SVIDs for each workload.
We'll walk through:

1. User login → gets token for Agent Orchestrator
2. Agent Orchestrator → Keycloak (token exchange to get token for Agent)
3. Agent → Keycloak (token exchange to get token for Tool)

Here's how it works, step by step:

* User Authentication

  The user logs in via the Login component, which redirects to Keycloak. Upon successful authentication, the user receives an OAuth2 access token, scoped only to the initial client (e.g., the Agent Orchestrator).

  ```shell
  POST /realms/agentic-platform/protocol/openid-connect/token
  Content-Type: application/x-www-form-urlencoded
  
  grant_type=authorization_code
  &client_id=frontend-ui
  &code=<auth_code>
  &redirect_uri=https://frontend.example.com/callback
  ```

  Response: User Access Token (JWT)

  ```json  
  {
    "access_token": "<JWT-USER-TOKEN>",
    "expires_in": 300,
    "scope": "openid profile",
    "token_type": "Bearer"
  }
  ```

  Decoded payload (`JWT-USER-TOKEN`):
  
  ```json
  {
    "sub": "user-123",
    "preferred_username": "maia",
    "aud": "agent-orchestrator",
    "exp": 1712345678,
    "roles": ["employee"]
  }
  ```  

* Client Self-Registration

  New agentic workloads (e.g., Agents, Tools) are dynamically provisioned by the platform. These workloads self-register as clients in Keycloak, presenting their SPIFFE identity.

  A human operator (or automated policy engine) then configures Token Exchange permissions in Keycloak, allowing specific clients to exchange tokens for specific downstream audiences. This enables decentralized provisioning with centralized policy enforcement.

* Workload Attestation

  The SPIRE Server attests the workloads: Agent Orchestrator, Agents, and Tools.

  Each workload receives a SPIFFE Verifiable Identity Document (SVID) – either a JWT or x.509 certificate – used to prove their identity to Keycloak and other services.

* Workload Authentication

  The Agent Orchestrator authenticates to Keycloak using its SVID. This replaces the need for static application secrets or long-lived credentials.

* Agent Orchestrator Requests Token Exchange ➝ Agent

  The orchestrator uses its own SPIFFE-issued identity, SVID, in form of JWT to access Keycloak as client and to exchange the user’s token for one scoped to the Agent (audience).

  ```shell
  POST /realms/agentic-platform/protocol/openid-connect/token
  Content-Type: application/x-www-form-urlencoded
  Authorization: Bearer <JWT-SVID-ORCHESTRATOR>
  
  grant_type=urn:ietf:params:oauth:grant-type:token-exchange
  &subject_token=<JWT-USER-TOKEN>
  &subject_token_type=urn:ietf:params:oauth:token-type:access_token
  &audience=agent-service
  &client_id=agent-orchestrator
  ```

  Keycloak verifies that:

  * The Orchestrator is a trusted client, by checking the provided SPIFFE ID with publicly available SPIRE OIDC service.
  * The token exchange for the Agent audience is permitted.
  A new token, scoped only for the Agent, is issued.

  Response: Token for Agent

  ```json  
  {
    "access_token": "<JWT-AGENT-TOKEN>",
    "expires_in": 300,
    "scope": "openid",
    "token_type": "Bearer"
  }
  ```

  Decoded payload (`JWT-AGENT-TOKEN`):
  
  ```json
  {
    "sub": "user-123",
    "act": {
      "sub": "spiffe://platform.example.com/ns/my-agents/sa/orchestrator"
    },
    "aud": "agent-service",
    "exp": 1712345899
  }
  ```

* Agent Requests Token Exchange ➝ Tool
  Agent repeats the process and it uses its own SPIFFE identity to exchange the received Agent-scoped token for one scoped to the Tool only (audience = Tool) and a short expiry.

  ```shell
    POST /realms/agentic-platform/protocol/openid-connect/token
    Content-Type: application/x-www-form-urlencoded
    Authorization: Bearer <JWT-SVID-AGENT>

    grant_type=urn:ietf:params:oauth:grant-type:token-exchange
    &subject_token=<JWT-AGENT-TOKEN>
    &subject_token_type=urn:ietf:params:oauth:token-type:access_token
    &audience=tool-service
    &client_id=agent-service
  ```

  Again, Keycloak verifies that:
  * The Agent is a trusted client via SPIFFE ID.
  * The token exchange for the Tool audience is permitted. A new token, scoped only for the Tool, is issued.

  Response: Token for Tool

  ```json
    {
    "access_token": "<JWT-TOOL-TOKEN>",
    "expires_in": 300,
    "scope": "openid",
    "token_type": "Bearer"
    }
  ```

  Decoded payload (`JWT-TOOL-TOKEN`):
  
  ```json
  {
   "sub": "user-123",
   "act": {
     "sub": "spiffe://platform.example.com/ns/my-agents/sa/agent"
     },
    "aud": "tool-service",
    "exp": 1712346044
  }
  ```

* Tool Enforces Access
  
  The Tool validates the token:
  * Verifies Keycloak’s signature.
  * Confirms audience and expiry.
  
  If needed, the Tool may request another token exchange for calling external APIs (e.g., HR systems, databases), using the same delegation and restriction mechanism.
