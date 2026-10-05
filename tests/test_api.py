"""Tests du client bas niveau de l'API Freebox OS."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from aioresponses import aioresponses
from yarl import URL

from custom_components.freebox_os.api import (
    FreeboxApiClient,
    FreeboxApiError,
    FreeboxAuthError,
    FreeboxConnectionError,
    FreeboxPermissionError,
    async_get_api_version,
    build_api_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOST = "mafreebox.freebox.fr"
API = "http://mafreebox.freebox.fr:80/api/v16/"
APP_ID = "fr.example.test"
APP_TOKEN = "app-token-for-tests"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def mock_login(m: aioresponses, challenge: str = "c1", session_token: str = "s1") -> None:
    m.get(f"{API}login/", payload={"success": True, "result": {"logged_in": False, "challenge": challenge}})
    m.post(
        f"{API}login/session/",
        payload={
            "success": True,
            "result": {"session_token": session_token, "challenge": challenge, "permissions": {"settings": True}},
        },
    )


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
def client(session: aiohttp.ClientSession) -> FreeboxApiClient:
    return FreeboxApiClient(session, API, APP_ID, APP_TOKEN)


def test_build_api_url_uses_major_version():
    assert build_api_url(HOST, 80, fixture("api_version")) == API
    assert build_api_url(HOST, 13812, {"api_version": "16.0"}, use_https=True) == (
        "https://mafreebox.freebox.fr:13812/api/v16/"
    )


@pytest.mark.asyncio
async def test_get_api_version(session: aiohttp.ClientSession):
    with aioresponses() as m:
        m.get(f"http://{HOST}:80/api_version", payload=fixture("api_version"))
        info = await async_get_api_version(session, HOST, 80)
    assert info["box_model"] == "fbxgw9-r1"


@pytest.mark.asyncio
async def test_get_api_version_rejects_non_freebox(session: aiohttp.ClientSession):
    with aioresponses() as m:
        m.get(f"http://{HOST}:80/api_version", payload={"hello": "world"})
        with pytest.raises(FreeboxApiError):
            await async_get_api_version(session, HOST, 80)


@pytest.mark.asyncio
async def test_get_api_version_unreachable(session: aiohttp.ClientSession):
    with aioresponses() as m:
        m.get(f"http://{HOST}:80/api_version", exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(FreeboxConnectionError):
            await async_get_api_version(session, HOST, 80)


@pytest.mark.asyncio
async def test_open_session_sends_hmac_of_challenge(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m, challenge="abc")
        await client.open_session()
        sent = m.requests[("POST", URL(f"{API}login/session/"))][0].kwargs["json"]
    expected = hmac.new(APP_TOKEN.encode(), b"abc", hashlib.sha1).hexdigest()
    assert sent == {"app_id": APP_ID, "password": expected}
    assert client.permissions == {"settings": True}


@pytest.mark.asyncio
async def test_open_session_revoked_token_raises_auth_error(client: FreeboxApiClient):
    with aioresponses() as m:
        m.get(f"{API}login/", payload={"success": True, "result": {"challenge": "c"}})
        m.post(
            f"{API}login/session/",
            status=403,
            payload={"success": False, "error_code": "invalid_token", "msg": "Invalid app token"},
        )
        with pytest.raises(FreeboxAuthError):
            await client.open_session()


@pytest.mark.asyncio
async def test_open_session_without_token(session: aiohttp.ClientSession):
    with pytest.raises(FreeboxAuthError):
        await FreeboxApiClient(session, API, APP_ID).open_session()


@pytest.mark.asyncio
async def test_request_logs_in_lazily_and_sends_session_header(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m, session_token="tok")
        m.get(f"{API}connection/", payload=fixture("connection"))
        result = await client.get_connection()
        headers = m.requests[("GET", URL(f"{API}connection/"))][0].kwargs["headers"]
    assert headers["X-Fbx-App-Auth"] == "tok"
    assert result["media"] == "ftth"
    assert result["bytes_down"] > 0


@pytest.mark.asyncio
async def test_request_reopens_expired_session_once(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m, session_token="old")
        m.get(
            f"{API}system/",
            status=403,
            payload={"success": False, "error_code": "auth_required", "msg": "Invalid session token"},
        )
        mock_login(m, session_token="new")
        m.get(f"{API}system/", payload=fixture("system"))
        result = await client.get_system()
        calls = m.requests[("GET", URL(f"{API}system/"))]
    assert [c.kwargs["headers"]["X-Fbx-App-Auth"] for c in calls] == ["old", "new"]
    assert {s["id"] for s in result["sensors"]} >= {"temp_cpu0", "temp_hdd"}


@pytest.mark.asyncio
async def test_request_insufficient_rights(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m)
        m.get(
            f"{API}system/",
            status=403,
            payload={"success": False, "error_code": "insufficient_rights", "msg": "Accès refusé"},
        )
        with pytest.raises(FreeboxPermissionError):
            await client.get_system()


@pytest.mark.asyncio
async def test_request_unknown_endpoint(client: FreeboxApiClient):
    # La v9 répond 404 invalid_request sur home/* (propre à la Delta).
    with aioresponses() as m:
        mock_login(m)
        m.get(f"{API}home/adapters/", status=404, payload={"success": False, "error_code": "invalid_request"})
        with pytest.raises(FreeboxApiError) as exc:
            await client.request("GET", "home/adapters/")
    assert exc.value.error_code == "invalid_request"


@pytest.mark.asyncio
async def test_request_non_json_response(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m)
        m.get(f"{API}system/", status=502, body="<html>Bad Gateway</html>")
        with pytest.raises(FreeboxApiError):
            await client.get_system()


@pytest.mark.asyncio
async def test_list_endpoints_default_to_empty(client: FreeboxApiClient):
    # Freebox OS omet `result` quand la liste est vide (vu sur vm/).
    with aioresponses() as m:
        mock_login(m)
        m.get(f"{API}storage/disk/", payload={"success": True})
        assert await client.get_storage_disks() == []


@pytest.mark.asyncio
async def test_authorize_flow(session: aiohttp.ClientSession):
    pairing = FreeboxApiClient(session, API, APP_ID)
    with aioresponses() as m:
        m.post(f"{API}login/authorize/", payload={"success": True, "result": {"app_token": "new-token", "track_id": 7}})
        m.get(f"{API}login/authorize/7", payload={"success": True, "result": {"status": "pending", "challenge": "x"}})
        m.get(f"{API}login/authorize/7", payload={"success": True, "result": {"status": "granted", "challenge": "x"}})
        track_id = await pairing.authorize("HA", "0.1.0", "Home Assistant")
        assert track_id == 7
        assert pairing.app_token == "new-token"
        assert await pairing.get_authorization_status(7) == "pending"
        assert await pairing.get_authorization_status(7) == "granted"


@pytest.mark.asyncio
async def test_close_session_is_best_effort(client: FreeboxApiClient):
    with aioresponses() as m:
        mock_login(m)
        await client.open_session()
        m.post(f"{API}login/logout/", exception=aiohttp.ClientConnectionError("down"))
        await client.close_session()  # ne lève pas
