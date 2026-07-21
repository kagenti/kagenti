import logging

import httpx

logger = logging.getLogger(__name__)


class TokenBrokerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(
                None, connect=10.0
            ),  # No timeout on requests, only on connect
        )

    async def create_session(self, jwt: str, redirect_url: str) -> bool:
        try:
            logger.info(
                f"Sending Token Broker session creation request to {self.base_url}/sessions"
            )
            resp = await self._client.post(
                "/sessions",
                headers={"Authorization": f"Bearer {jwt}"},
                json={"backend_session_redirect_url": redirect_url},
            )
            if resp.status_code == 201:
                logger.info("Token Broker session created successfully (201)")
                return True
            else:
                logger.warning(
                    f"Token Broker session creation failed with status {resp.status_code}"
                )
                return False
        except httpx.RequestError as e:
            logger.warning("Token Broker create_session failed: %s", e)
            return False

    async def poll_events(self, jwt: str) -> dict | None:
        """Poll Token Broker for broker-events (no timeout, waits indefinitely).

        Returns:
            dict: Event data if available
            None: No events available (204 response)

        Raises:
            httpx.HTTPStatusError: For error status codes (including 404)
            httpx.RequestError: For network/connection errors
        """
        resp = await self._client.post(
            "/sessions/broker-events",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        event = resp.json()
        logger.info(
            f"Token Broker broker-event received: {event.get('event_type', 'unknown')}"
        )
        return event

    async def end_session(self, jwt: str) -> None:
        try:
            await self._client.post(
                "/sessions/end",
                headers={"Authorization": f"Bearer {jwt}"},
            )
        except httpx.RequestError as e:
            logger.warning("Token Broker end_session error: %s", e)

    async def close(self) -> None:
        await self._client.aclose()
