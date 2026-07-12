# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the simulation harness HTTP client (issue #2162)."""

from unittest.mock import patch

import httpx
import pytest

from app.services import simulation_harness_client as hc


class _FakeResp:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.posted = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if self._exc:
            raise self._exc
        return self._resp

    async def post(self, url, json=None):
        if self._exc:
            raise self._exc
        self.posted = json
        return self._resp


@pytest.mark.asyncio
async def test_get_simulation_returns_parsed_body():
    fake = _FakeClient(resp=_FakeResp(200, {"status": "ready", "mcp_url": "u"}))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        body = await hc.get_simulation("http://sim")
    assert body["status"] == "ready"


@pytest.mark.asyncio
async def test_get_simulation_raises_not_found_on_404():
    fake = _FakeClient(resp=_FakeResp(404))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        with pytest.raises(hc.HarnessNotFound):
            await hc.get_simulation("http://sim")


@pytest.mark.asyncio
async def test_get_simulation_raises_unreachable_on_connect_error():
    fake = _FakeClient(exc=httpx.ConnectError("boom"))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        with pytest.raises(hc.HarnessUnreachable):
            await hc.get_simulation("http://sim")


@pytest.mark.asyncio
async def test_post_simulation_sends_spec_and_name_and_returns_code():
    fake = _FakeClient(resp=_FakeResp(202))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        code = await hc.post_simulation("http://sim", {"openapi": "3.0.0"}, "petstore")
    assert code == 202
    assert fake.posted == {"openapi_spec": {"openapi": "3.0.0"}, "name": "petstore"}


@pytest.mark.asyncio
async def test_post_simulation_raises_unreachable_on_timeout():
    fake = _FakeClient(exc=httpx.TimeoutException("slow"))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        with pytest.raises(hc.HarnessUnreachable):
            await hc.post_simulation("http://sim", {}, "x")


@pytest.mark.asyncio
async def test_reset_simulation_returns_status_code():
    fake = _FakeClient(resp=_FakeResp(200, {"message": "Session reset successfully"}))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        code = await hc.reset_simulation("http://sim")
    assert code == 200


@pytest.mark.asyncio
async def test_reset_simulation_passes_through_404():
    fake = _FakeClient(resp=_FakeResp(404))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        code = await hc.reset_simulation("http://sim")
    assert code == 404


@pytest.mark.asyncio
async def test_reset_simulation_raises_unreachable_on_connect_error():
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    with patch.object(hc.httpx, "AsyncClient", lambda **kw: fake):
        with pytest.raises(hc.HarnessUnreachable):
            await hc.reset_simulation("http://sim")
