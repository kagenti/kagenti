"""
Unit tests for the OpenShell gateway gRPC client.

Verifies TLS credential loading, channel caching, ExecSandbox streaming,
and error handling without requiring a running gateway.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.openshell.gateway import OpenShellGatewayClient


@pytest.fixture
def gateway():
    return OpenShellGatewayClient()


@pytest.fixture
def mock_secret():
    """Fake openshell-client-tls secret with base64-encoded test data."""
    test_data = base64.b64encode(b"test-tls-data-not-a-real-credential").decode()
    secret = MagicMock()
    secret.data = {"tls.crt": test_data, "tls.key": test_data, "ca.crt": test_data}
    return secret


class TestTLSCredentials:
    def test_loads_tls_from_k8s_secret(self, gateway, mock_secret):
        with (
            patch("app.services.openshell.gateway.get_kubernetes_service") as mock_kube,
            patch("app.services.openshell.gateway.grpc.ssl_channel_credentials") as mock_ssl,
        ):
            mock_kube.return_value.core_api.read_namespaced_secret.return_value = mock_secret
            mock_ssl.return_value = MagicMock()

            creds = gateway._load_tls_credentials("team1")

            mock_kube.return_value.core_api.read_namespaced_secret.assert_called_once_with(
                name="openshell-client-tls", namespace="team1"
            )
            mock_ssl.assert_called_once()
            assert creds is not None

    def test_caches_tls_credentials(self, gateway, mock_secret):
        with (
            patch("app.services.openshell.gateway.get_kubernetes_service") as mock_kube,
            patch("app.services.openshell.gateway.grpc.ssl_channel_credentials") as mock_ssl,
        ):
            mock_kube.return_value.core_api.read_namespaced_secret.return_value = mock_secret
            mock_ssl.return_value = MagicMock()

            gateway._load_tls_credentials("team1")
            gateway._load_tls_credentials("team1")

            assert mock_kube.return_value.core_api.read_namespaced_secret.call_count == 1

    def test_cache_expires_after_ttl(self, gateway, mock_secret):
        with (
            patch("app.services.openshell.gateway.get_kubernetes_service") as mock_kube,
            patch("app.services.openshell.gateway.grpc.ssl_channel_credentials") as mock_ssl,
            patch("app.services.openshell.gateway.time") as mock_time,
        ):
            mock_kube.return_value.core_api.read_namespaced_secret.return_value = mock_secret
            mock_ssl.return_value = MagicMock()

            mock_time.monotonic.return_value = 0.0
            gateway._load_tls_credentials("team1")

            mock_time.monotonic.return_value = 301.0
            gateway._load_tls_credentials("team1")

            assert mock_kube.return_value.core_api.read_namespaced_secret.call_count == 2

    def test_separate_cache_per_namespace(self, gateway, mock_secret):
        with (
            patch("app.services.openshell.gateway.get_kubernetes_service") as mock_kube,
            patch("app.services.openshell.gateway.grpc.ssl_channel_credentials") as mock_ssl,
        ):
            mock_kube.return_value.core_api.read_namespaced_secret.return_value = mock_secret
            mock_ssl.return_value = MagicMock()

            gateway._load_tls_credentials("team1")
            gateway._load_tls_credentials("team2")

            assert mock_kube.return_value.core_api.read_namespaced_secret.call_count == 2


class TestExecSandbox:
    @pytest.mark.asyncio
    async def test_streams_stdout_events(self, gateway):
        mock_event_stdout = MagicMock()
        mock_event_stdout.WhichOneof.return_value = "stdout"
        mock_event_stdout.stdout.data = b"Hello from sandbox"

        mock_event_exit = MagicMock()
        mock_event_exit.WhichOneof.return_value = "exit"
        mock_event_exit.exit.exit_code = 0

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(
            side_effect=[mock_event_stdout, mock_event_exit, StopAsyncIteration]
        )

        with (
            patch.object(gateway, "_get_channel"),
            patch.object(gateway, "_get_oidc_token", return_value="mock-token"),
            patch("app.services.openshell.v1.exec_pb2_grpc.OpenShellStub") as mock_stub_cls,
        ):
            mock_stub = MagicMock()
            mock_stub.ExecSandbox.return_value = mock_stream
            mock_stub_cls.return_value = mock_stub

            events = []
            async for ev in gateway.exec_sandbox(
                sandbox_id="openshell-claude",
                namespace="team1",
                command=["claude", "--print", "hello"],
            ):
                events.append(ev)

            assert len(events) == 2
            assert events[0] == ("stdout", b"Hello from sandbox")
            assert events[1] == ("exit", 0)

    @pytest.mark.asyncio
    async def test_streams_stderr_events(self, gateway):
        mock_event_stderr = MagicMock()
        mock_event_stderr.WhichOneof.return_value = "stderr"
        mock_event_stderr.stderr.data = b"warning: something"

        mock_event_exit = MagicMock()
        mock_event_exit.WhichOneof.return_value = "exit"
        mock_event_exit.exit.exit_code = 1

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream.__anext__ = AsyncMock(
            side_effect=[mock_event_stderr, mock_event_exit, StopAsyncIteration]
        )

        with (
            patch.object(gateway, "_get_channel"),
            patch.object(gateway, "_get_oidc_token", return_value="mock-token"),
            patch("app.services.openshell.v1.exec_pb2_grpc.OpenShellStub") as mock_stub_cls,
        ):
            mock_stub = MagicMock()
            mock_stub.ExecSandbox.return_value = mock_stream
            mock_stub_cls.return_value = mock_stub

            events = []
            async for ev in gateway.exec_sandbox(
                sandbox_id="openshell-opencode",
                namespace="team1",
                command=["opencode", "run", "hello"],
            ):
                events.append(ev)

            assert events[0] == ("stderr", b"warning: something")
            assert events[1] == ("exit", 1)


class TestChannelManagement:
    def test_caches_channel_per_namespace(self, gateway):
        with (
            patch.object(gateway, "_load_tls_credentials") as mock_tls,
            patch("app.services.openshell.gateway.grpc.aio.secure_channel") as mock_chan,
        ):
            mock_tls.return_value = MagicMock()
            mock_chan.return_value = MagicMock()

            ch1 = gateway._get_channel("team1")
            ch2 = gateway._get_channel("team1")

            assert ch1 is ch2
            assert mock_chan.call_count == 1

    def test_separate_channels_per_namespace(self, gateway):
        with (
            patch.object(gateway, "_load_tls_credentials") as mock_tls,
            patch("app.services.openshell.gateway.grpc.aio.secure_channel") as mock_chan,
        ):
            mock_tls.return_value = MagicMock()
            mock_chan.return_value = MagicMock()

            gateway._get_channel("team1")
            gateway._get_channel("team2")

            assert mock_chan.call_count == 2

    @pytest.mark.asyncio
    async def test_close_clears_all_channels(self, gateway):
        mock_channel = AsyncMock()
        gateway._channels = {"team1": mock_channel, "team2": mock_channel}
        gateway._tls_cache = {"team1": (0.0, MagicMock())}

        await gateway.close()

        assert len(gateway._channels) == 0
        assert len(gateway._tls_cache) == 0
        assert mock_channel.close.await_count == 2
