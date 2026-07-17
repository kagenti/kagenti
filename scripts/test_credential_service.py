#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Test credential validation service for rossocortex agent testing.

Accepts requests and validates the Authorization: Bearer header against
a known expected key. Used to verify that rossocortex/authbridge correctly
injects credentials for a given agent.

Usage:
    ./test_credential_service.py --port 9999 --expected-key sk-test-secret-123
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class CredentialHandler(BaseHTTPRequestHandler):
    expected_key: str

    def log_message(self, format, *args):
        sys.stderr.write(f"[test-service] {format % args}\n")

    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"status": "healthy"})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/validate":
            self._handle_validate()
        else:
            self._json_response(404, {"error": "not found"})

    def _handle_validate(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._json_response(401, {
                "error": "unauthorized",
                "detail": "missing or malformed Authorization header",
                "received": auth[:20] + "..." if len(auth) > 20 else auth,
            })
            return

        token = auth[7:]
        if token == self.expected_key:
            self._json_response(200, {
                "status": "ok",
                "credential_received": True,
                "key_prefix": token[:8] + "...",
            })
        else:
            masked = token[:4] + "****" + token[-4:] if len(token) > 8 else "****"
            self._json_response(401, {
                "error": "unauthorized",
                "detail": "credential does not match expected key",
                "received": masked,
            })

    def _json_response(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    parser = argparse.ArgumentParser(description="Test credential validation service")
    parser.add_argument("--port", type=int, default=9999, help="Listen port (default: 9999)")
    parser.add_argument("--expected-key", required=True, help="The credential value to accept as valid")
    args = parser.parse_args()

    CredentialHandler.expected_key = args.expected_key

    server = HTTPServer(("0.0.0.0", args.port), CredentialHandler)
    print(f"Test credential service listening on :{args.port}")
    print(f"  GET  /health   — always 200")
    print(f"  POST /validate — checks Authorization: Bearer against expected key")
    print(f"  Expected key:  {args.expected_key[:8]}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
