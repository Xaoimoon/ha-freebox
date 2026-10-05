"""Tests du coordinateur : assemblage des relevés, droits manquants, erreurs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.freebox_os.api import (
    FreeboxApiError,
    FreeboxAuthError,
    FreeboxConnectionError,
    FreeboxPermissionError,
)
from custom_components.freebox_os.coordinator import FreeboxDataUpdateCoordinator

FIXTURES = Path(__file__).parent / "fixtures"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def make_api() -> AsyncMock:
    api = AsyncMock()
    api.get_system.return_value = result("system")
    api.get_connection.return_value = result("connection")
    api.get_connection_logs.return_value = result("connection_logs")
    api.get_connection_ftth.return_value = result("connection_ftth")
    api.get_switch_status.return_value = result("switch_status")
    api.get_switch_port_stats.return_value = result("switch_port_stats")
    api.get_storage_disks.return_value = result("storage_disk")
    api.get_storage_raids.return_value = []
    api.get_lan_interfaces.return_value = result("lan_browser_interfaces")
    api.get_lan_hosts.return_value = result("lan_browser_pub")
    api.get_call_log.return_value = result("call_log")
    api.get_wifi_config.return_value = result("wifi_config")
    return api


def make_coordinator(api: AsyncMock) -> FreeboxDataUpdateCoordinator:
    return FreeboxDataUpdateCoordinator(MagicMock(), MagicMock(), api)


@pytest.mark.asyncio
async def test_full_snapshot():
    api = make_api()
    data = await make_coordinator(api)._async_update_data()

    assert data.system["model_info"]["name"] == "fbxgw9-r1"
    assert set(data.hosts) == {"00:00:5E:00:53:10", "00:00:5E:00:53:11", "00:00:5E:00:53:12"}
    assert list(data.disks) == [1000]
    assert data.calls and data.calls[0]["type"] == "missed"
    assert data.wifi == {"enabled": False, "power_saving": True, "mac_filter_state": "disabled"}
    # `wifiguest` est vide (host_count 0) : pas interrogé.
    api.get_lan_hosts.assert_awaited_once_with("pub")


@pytest.mark.asyncio
async def test_missing_permissions_disable_optional_parts():
    api = make_api()
    api.get_call_log.side_effect = FreeboxPermissionError("x", "insufficient_rights")
    api.get_wifi_config.side_effect = FreeboxPermissionError("x", "insufficient_rights")
    coordinator = make_coordinator(api)

    data = await coordinator._async_update_data()
    assert data.calls is None and data.wifi is None

    # Plus redemandé aux relevés suivants.
    await coordinator._async_update_data()
    assert api.get_call_log.await_count == 1
    assert api.get_wifi_config.await_count == 1


@pytest.mark.asyncio
async def test_bridge_mode_has_no_hosts():
    api = make_api()
    api.get_lan_interfaces.side_effect = FreeboxApiError("x", "nodev")
    coordinator = make_coordinator(api)

    data = await coordinator._async_update_data()
    assert data.hosts == {}
    assert coordinator.supports_hosts is False


@pytest.mark.asyncio
async def test_revoked_token_triggers_reauth():
    api = make_api()
    api.get_system.side_effect = FreeboxAuthError("x", "invalid_token")
    with pytest.raises(ConfigEntryAuthFailed):
        await make_coordinator(api)._async_update_data()


@pytest.mark.asyncio
async def test_unreachable_box_is_update_failed():
    api = make_api()
    api.get_connection.side_effect = FreeboxConnectionError("down")
    with pytest.raises(UpdateFailed):
        await make_coordinator(api)._async_update_data()
