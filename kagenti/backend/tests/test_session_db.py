# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for session_db pool management.

Verifies:
- Pool creation with ssl=False for Istio compatibility
- Retry on transient connection failures
- No retry on auth/catalog errors (non-transient)
- Stale pool eviction
- Closed pool detection and recreation
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("app.services.session_db", reason="session_db module not available")


class TestCreatePool:
    """Tests for _create_pool() with retry and SSL handling."""

    @pytest.fixture(autouse=True)
    def reset_pool_cache(self):
        """Clear pool cache before each test."""
        from app.services.session_db import _pool_cache

        _pool_cache.clear()
        yield
        _pool_cache.clear()

    @pytest.mark.asyncio
    async def test_pool_created_with_ssl_false(self):
        """Pool creation should pass ssl=False for Istio ambient compatibility."""
        mock_pool = MagicMock()
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

            from app.services.session_db import _create_pool

            pool = await _create_pool("postgresql://user:pass@host:5432/db")
            assert pool is mock_pool

            call_kwargs = mock_asyncpg.create_pool.call_args
            assert call_kwargs.kwargs["ssl"] is False

    @pytest.mark.asyncio
    async def test_pool_created_with_command_timeout(self):
        """Pool creation should set command_timeout to prevent hanging queries."""
        mock_pool = MagicMock()
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

            from app.services.session_db import _create_pool

            await _create_pool("postgresql://user:pass@host:5432/db")

            call_kwargs = mock_asyncpg.create_pool.call_args
            assert call_kwargs.kwargs["command_timeout"] == 30

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """Pool creation should retry on transient connection errors."""
        mock_pool = MagicMock()
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            # Fail twice, succeed on third attempt
            mock_asyncpg.create_pool = AsyncMock(
                side_effect=[
                    ConnectionError("Connection refused"),
                    OSError("Network unreachable"),
                    mock_pool,
                ]
            )
            mock_asyncpg.InvalidPasswordError = type("InvalidPasswordError", (Exception,), {})
            mock_asyncpg.InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})

            from app.services.session_db import _create_pool

            with patch("app.services.session_db._POOL_RETRY_DELAY", 0.01):
                pool = await _create_pool("postgresql://user:pass@host:5432/db")

            assert pool is mock_pool
            assert mock_asyncpg.create_pool.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self):
        """Pool creation should NOT retry on InvalidPasswordError."""
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            InvalidPasswordError = type("InvalidPasswordError", (Exception,), {})  # noqa: N806
            mock_asyncpg.InvalidPasswordError = InvalidPasswordError
            mock_asyncpg.InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})
            mock_asyncpg.create_pool = AsyncMock(side_effect=InvalidPasswordError("wrong password"))

            from app.services.session_db import _create_pool

            with pytest.raises(InvalidPasswordError):
                await _create_pool("postgresql://user:wrong@host:5432/db")

            # Should fail immediately — no retries
            assert mock_asyncpg.create_pool.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_catalog_error(self):
        """Pool creation should NOT retry on InvalidCatalogNameError."""
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})  # noqa: N806
            mock_asyncpg.InvalidPasswordError = type("InvalidPasswordError", (Exception,), {})
            mock_asyncpg.InvalidCatalogNameError = InvalidCatalogNameError
            mock_asyncpg.create_pool = AsyncMock(
                side_effect=InvalidCatalogNameError("DB not found")
            )

            from app.services.session_db import _create_pool

            with pytest.raises(InvalidCatalogNameError):
                await _create_pool("postgresql://user:pass@host:5432/nope")

            assert mock_asyncpg.create_pool.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Pool creation should raise after exhausting retries."""
        with patch("app.services.session_db.asyncpg") as mock_asyncpg:
            mock_asyncpg.InvalidPasswordError = type("InvalidPasswordError", (Exception,), {})
            mock_asyncpg.InvalidCatalogNameError = type("InvalidCatalogNameError", (Exception,), {})
            mock_asyncpg.create_pool = AsyncMock(side_effect=ConnectionError("Connection refused"))

            from app.services.session_db import _create_pool

            with patch("app.services.session_db._POOL_RETRY_DELAY", 0.01):
                with pytest.raises(ConnectionError):
                    await _create_pool("postgresql://user:pass@host:5432/db")

            assert mock_asyncpg.create_pool.call_count == 3


class TestGetSessionPool:
    """Tests for get_session_pool() caching and stale pool detection."""

    @pytest.fixture(autouse=True)
    def reset_pool_cache(self):
        """Clear pool cache before each test."""
        from app.services.session_db import _pool_cache

        _pool_cache.clear()
        yield
        _pool_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_cached_pool(self):
        """get_session_pool() should return cached pool on subsequent calls."""
        mock_pool = MagicMock()
        mock_pool._closed = False

        from app.services.session_db import _pool_cache, get_session_pool

        _pool_cache["team1"] = mock_pool

        pool = await get_session_pool("team1")
        assert pool is mock_pool

    @pytest.mark.asyncio
    async def test_recreates_closed_pool(self):
        """get_session_pool() should recreate a pool that was externally closed."""
        old_pool = MagicMock()
        old_pool._closed = True

        new_pool = MagicMock()
        new_pool._closed = False

        from app.services.session_db import _pool_cache, get_session_pool

        _pool_cache["team1"] = old_pool

        with patch("app.services.session_db._create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = new_pool
            with patch("app.services.session_db._dsn_for_namespace", return_value="postgresql://x"):
                pool = await get_session_pool("team1")

            assert pool is new_pool
            assert _pool_cache["team1"] is new_pool
            mock_create.assert_called_once()


class TestEvictPool:
    """Tests for evict_pool() cache invalidation."""

    @pytest.fixture(autouse=True)
    def reset_pool_cache(self):
        from app.services.session_db import _pool_cache

        _pool_cache.clear()
        yield
        _pool_cache.clear()

    @pytest.mark.asyncio
    async def test_evict_removes_from_cache(self):
        """evict_pool() should remove the pool from cache and close it."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()

        from app.services.session_db import _pool_cache, evict_pool

        _pool_cache["team1"] = mock_pool

        await evict_pool("team1")

        assert "team1" not in _pool_cache
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_evict_nonexistent_is_noop(self):
        """evict_pool() on a namespace without a pool should be a no-op."""
        from app.services.session_db import evict_pool

        # Should not raise
        await evict_pool("nonexistent")

    @pytest.mark.asyncio
    async def test_evict_survives_close_error(self):
        """evict_pool() should still remove from cache even if close() fails."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock(side_effect=RuntimeError("close failed"))

        from app.services.session_db import _pool_cache, evict_pool

        _pool_cache["team1"] = mock_pool

        await evict_pool("team1")

        assert "team1" not in _pool_cache
