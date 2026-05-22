# OAuth Token Propagation Implementation

## Overview
This document describes the implementation of OAuth token propagation from ui-v2 to agents via the backend, enabling authenticated agent communication.

## Architecture

### Flow
1. User authenticates with Keycloak in ui-v2
2. Access token is stored in React state + sessionStorage
3. Token is automatically injected into API requests (Authorization: Bearer {token})
4. Backend forwards Authorization header to agents via A2A protocol
5. Agents can validate token and access user context

## Components Modified

### Frontend (ui-v2)

#### 1. AuthContext.tsx
**Changes:**
- Added token storage in `sessionStorage` alongside React state for persistence
- Enhanced `getToken()` to use sessionStorage as fallback when Keycloak not available
- Updated token refresh logic to sync with sessionStorage
- Added sessionStorage cleanup on logout

**Key Code:**
```typescript
// Store token on authentication
if (accessToken) {
  sessionStorage.setItem('kagenti_access_token', accessToken);
}

// Fallback to sessionStorage in getToken()
const storedToken = sessionStorage.getItem('kagenti_access_token');
return storedToken || null;

// Clear on logout
sessionStorage.removeItem('kagenti_access_token');
```

#### 2. AgentChat.tsx
**Changes:**
- Added `useAuth()` hook to access token getter
- Modified chat streaming to include Authorization header
- Token is fetched before each chat request and included in fetch headers

**Key Code:**
```typescript
const { getToken } = useAuth();

// Get auth token if available
const token = await getToken();
const headers: Record<string, string> = {
  'Content-Type': 'application/json',
};
if (token) {
  headers['Authorization'] = `Bearer ${token}`;
}

const response = await fetch(
  `/api/v1/chat/${namespace}/${name}/stream`,
  { method: 'POST', headers, body: JSON.stringify(...) }
);
```

### Backend (FastAPI)

#### 3. chat.py
**Changes:**
- Added `Request` import to access HTTP headers
- Modified `send_message()` endpoint to extract and forward Authorization header
- Modified `stream_message()` endpoint to extract and forward Authorization header
- Updated `_stream_a2a_response()` helper to accept and forward authorization parameter

**Key Code:**
```python
from fastapi import APIRouter, HTTPException, Request

@router.post("/{namespace}/{name}/stream")
async def stream_message(
    namespace: str,
    name: str,
    request: ChatRequest,
    http_request: Request,  # Added to access headers
):
    # Extract Authorization header if present
    authorization = http_request.headers.get("Authorization")
    
    return StreamingResponse(
        _stream_a2a_response(agent_url, request.message, session_id, authorization),
        ...
    )

async def _stream_a2a_response(
    agent_url: str, 
    message: str, 
    session_id: str, 
    authorization: Optional[str] = None  # Added parameter
):
    # Prepare headers with optional Authorization
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if authorization:
        headers["Authorization"] = authorization
        logger.info("Forwarding Authorization header to agent")
    
    async with client.stream("POST", agent_url, json=message_payload, headers=headers):
        ...
```

## Security Considerations

### Token Storage
- **Memory (React State)**: Primary storage, cleared on page refresh
- **sessionStorage**: Backup storage, persists during tab session, cleared on tab close
- **Not in localStorage**: Avoided for security (localStorage persists indefinitely)

### Token Validation
- Frontend: Token validation happens via Keycloak refresh mechanism
- Backend: Currently passes through token without validation (Zero Trust deferred to agents)
- Agents: Can validate token against Keycloak using JWKS endpoint if needed

### HTTPS
- Production deployments should use HTTPS to encrypt token transmission
- Bearer tokens in Authorization headers are vulnerable to interception without TLS

## Testing

### Manual Testing Steps

1. **Verify Token Storage:**
   ```javascript
   // In browser console after login
   sessionStorage.getItem('kagenti_access_token')
   ```

2. **Verify Token in Requests:**
   - Open browser DevTools → Network tab
   - Send a chat message to an agent
   - Inspect `/api/v1/chat/{namespace}/{name}/stream` request
   - Check Request Headers for `Authorization: Bearer {token}`

3. **Verify Backend Forwarding:**
   - Check backend logs for "Forwarding Authorization header to agent"
   - Agent logs should show received Authorization header

4. **Test Token Refresh:**
   - Wait for token to expire (default ~5 minutes)
   - Send another chat message
   - Verify token is refreshed and new token is used

5. **Test Logout:**
   - Logout from ui-v2
   - Verify sessionStorage is cleared
   - Verify new login gets fresh token

## Agent-Side Implementation

To use the forwarded token in agents, agents need to:

1. **Extract token from headers:**
   ```python
   from fastapi import Header, HTTPException
   
   async def handle_message(authorization: str = Header(None)):
       if not authorization:
           raise HTTPException(401, "Unauthorized")
       
       token = authorization.replace("Bearer ", "")
       # Validate token...
   ```

2. **Validate token against Keycloak:**
   ```python
   from jose import jwt
   
   KEYCLOAK_PUBLIC_KEY = "..."  # Fetch from JWKS endpoint
   
   def validate_token(token: str):
       try:
           payload = jwt.decode(token, KEYCLOAK_PUBLIC_KEY, algorithms=["RS256"])
           return payload  # Contains user info, roles, etc.
       except jwt.JWTError:
           raise HTTPException(401, "Invalid token")
   ```

3. **Use user context:**
   ```python
   payload = validate_token(token)
   user_email = payload.get("email")
   user_roles = payload.get("realm_access", {}).get("roles", [])
   ```

## Future Enhancements

1. **Backend Token Validation:**
   - Add middleware to validate tokens at backend layer
   - Cache JWKS keys from Keycloak
   - Return 401 if token is invalid or expired

2. **Token Refresh Handling:**
   - Implement automatic retry on 401 with token refresh
   - Add exponential backoff for failed token refreshes

3. **Axios Interceptor (Optional):**
   - Currently using fetch API with manual header injection
   - Could migrate to axios with request/response interceptors for cleaner code

4. **Agent Authentication Library:**
   - Create shared library for agents to validate tokens
   - Standardize user context extraction
   - Support multiple auth providers (Keycloak, Auth0, etc.)

## References

- [Keycloak Documentation](https://www.keycloak.org/docs/latest/)
- [A2A Protocol Specification](../docs/a2a-protocol.md)
- [OAuth 2.0 Bearer Tokens (RFC 6750)](https://datatracker.ietf.org/doc/html/rfc6750)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)

## Changelog

- **2025-01-XX**: Initial implementation
  - Token storage in AuthContext with sessionStorage backup
  - Authorization header injection in chat streaming
  - Backend forwarding to agents via A2A protocol
