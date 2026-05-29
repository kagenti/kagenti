"""
OpenShell gateway gRPC client.

Routes sandbox agent prompts through the OpenShell gateway's ExecSandbox RPC
instead of kubectl exec, providing session management, credential injection,
and audit logging.
"""

import base64
import logging
import time
from functools import lru_cache
from typing import AsyncIterator

import grpc

from app.services.kubernetes import get_kubernetes_service
from app.services.openshell.v1 import exec_pb2, exec_pb2_grpc

logger = logging.getLogger(__name__)

GATEWAY_SERVICE = "openshell-server"
GATEWAY_PORT = 8080
CLIENT_TLS_SECRET = "openshell-client-tls"
TLS_CACHE_TTL = 300


class OpenShellGatewayClient:
    """gRPC client for the OpenShell gateway ExecSandbox RPC."""

    def __init__(self):
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._tls_cache: dict[str, tuple[float, grpc.ChannelCredentials]] = {}

    def _load_tls_credentials(self, namespace: str) -> grpc.ChannelCredentials:
        cached = self._tls_cache.get(namespace)
        if cached and (time.monotonic() - cached[0]) < TLS_CACHE_TTL:
            return cached[1]

        logger.info(
            "Loading TLS credentials",
            extra={"namespace": namespace, "secret": CLIENT_TLS_SECRET},
        )
        kube = get_kubernetes_service()
        secret = kube.core_api.read_namespaced_secret(name=CLIENT_TLS_SECRET, namespace=namespace)
        cert = base64.b64decode(secret.data["tls.crt"])
        key = base64.b64decode(secret.data["tls.key"])
        ca = base64.b64decode(secret.data["ca.crt"])

        creds = grpc.ssl_channel_credentials(
            root_certificates=ca,
            private_key=key,
            certificate_chain=cert,
        )
        self._tls_cache[namespace] = (time.monotonic(), creds)
        return creds

    def _get_channel(self, namespace: str) -> grpc.aio.Channel:
        if namespace in self._channels:
            return self._channels[namespace]

        creds = self._load_tls_credentials(namespace)
        target = f"{GATEWAY_SERVICE}.{namespace}.svc:{GATEWAY_PORT}"
        logger.info(
            "Creating gRPC channel",
            extra={"target": target, "namespace": namespace},
        )
        channel = grpc.aio.secure_channel(target, creds)
        self._channels[namespace] = channel
        return channel

    async def exec_sandbox(
        self,
        sandbox_id: str,
        namespace: str,
        command: list[str],
        timeout_seconds: int = 120,
        workdir: str = "",
        environment: dict[str, str] | None = None,
    ) -> AsyncIterator[tuple[str, bytes | int]]:
        """Execute a command in a sandbox via the gateway's ExecSandbox RPC.

        Yields tuples of (event_type, data):
          ("stdout", bytes) — stdout chunk
          ("stderr", bytes) — stderr chunk
          ("exit", int)     — exit code
        """
        channel = self._get_channel(namespace)
        stub = exec_pb2_grpc.OpenShellStub(channel)

        logger.info(
            "ExecSandbox request",
            extra={
                "sandbox_id": sandbox_id,
                "namespace": namespace,
                "command_count": len(command),
                "timeout_seconds": timeout_seconds,
            },
        )

        request = exec_pb2.ExecSandboxRequest(
            sandbox_id=sandbox_id,
            command=command,
            workdir=workdir,
            environment=environment or {},
            timeout_seconds=timeout_seconds,
            tty=False,
        )

        try:
            response_stream = stub.ExecSandbox(request)
            chunk_count = 0
            async for event in response_stream:
                payload = event.WhichOneof("payload")
                if payload == "stdout":
                    chunk_count += 1
                    yield ("stdout", event.stdout.data)
                elif payload == "stderr":
                    yield ("stderr", event.stderr.data)
                elif payload == "exit":
                    logger.info(
                        "ExecSandbox completed",
                        extra={
                            "sandbox_id": sandbox_id,
                            "exit_code": event.exit.exit_code,
                            "stdout_chunks": chunk_count,
                        },
                    )
                    yield ("exit", event.exit.exit_code)
        except grpc.aio.AioRpcError as e:
            logger.error(
                "ExecSandbox gRPC error",
                extra={
                    "sandbox_id": sandbox_id,
                    "namespace": namespace,
                    "grpc_code": e.code().name,
                    "grpc_details": str(e.details())[:200],
                },
            )
            if e.code() == grpc.StatusCode.UNAUTHENTICATED:
                self._tls_cache.pop(namespace, None)
                self._channels.pop(namespace, None)
                logger.warning(
                    "Evicted cached TLS credentials after auth failure",
                    extra={"namespace": namespace},
                )
            raise

    async def close(self):
        logger.info("Closing gateway channels", extra={"count": len(self._channels)})
        for channel in self._channels.values():
            await channel.close()
        self._channels.clear()
        self._tls_cache.clear()


@lru_cache
def get_openshell_client() -> OpenShellGatewayClient:
    return OpenShellGatewayClient()
