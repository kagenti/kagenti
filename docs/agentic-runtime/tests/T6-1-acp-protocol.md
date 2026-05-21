# ACP Protocol

> **Test file:** `kagenti/tests/e2e/openshell/test_T6_1_acp_protocol.py`
> **Tests:** 12

## What This Tests

Validates the ACP (Agent Client Protocol) WebSocket endpoint at `/api/v1/acp/ws/{namespace}/{agent_name}`. Tests the full JSON-RPC 2.0 lifecycle: initialize handshake, session creation/listing/resume/close, prompt relay to A2A agents with streaming updates, multi-turn context preservation through the ACP-to-A2A bridge, permission request handling, concurrent independent sessions, and error responses for malformed JSON-RPC and unknown methods.

## Test Functions

- `test_T6_lifecycle__initialize` -- WebSocket connect and `initialize` handshake returns capabilities (protocolVersion or agentCapabilities).
- `test_T6_lifecycle__session_new` -- `session/new` returns a non-empty `sessionId`.
- `test_T6_lifecycle__session_close` -- `session/close` with a valid sessionId returns `closed: true`.
- `test_T6_prompt__text_response[agent]` -- Send a prompt via `session/prompt` and receive streaming `session/update` events with text content.
- `test_T6_bridge__acp_to_a2a[agent]` -- Full roundtrip: ACP client sends prompt over WebSocket, backend bridges to A2A agent, response arrives as turn_complete.
- `test_T6_bridge__context_preserved[agent]` -- Multi-turn conversation via ACP maintains context across sequential prompts within the same session.
- `test_T6_session__list` -- `session/list` returns all sessions created on the connection.
- `test_T6_session__resume` -- `session/resume` with an existing sessionId returns `resumed: true`.
- `test_T6_permission__request` -- `session/request_permission` auto-approves with `outcome: selected` and `selectedOptionId: allow_once` in PoC mode.
- `test_T6_concurrent__sessions` -- Two independent WebSocket clients get distinct session IDs and operate without interference.
- `test_T6_error__malformed_rpc` -- Sending invalid JSON returns a JSON-RPC parse error (code -32700).
- `test_T6_error__unknown_method` -- Calling an unknown method returns a method-not-found error (code -32601).
