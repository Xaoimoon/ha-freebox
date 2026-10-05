"""Tests du contrôle parental : profils, actions, découverte, suppression d'appareils."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
from yarl import URL

from custom_components.freebox_os import (
    async_remove_config_entry_device,
    button,
    sensor,
    services,
    switch,
)
from custom_components.freebox_os.api import FreeboxApiClient, FreeboxPermissionError
from custom_components.freebox_os.const import DOMAIN
from custom_components.freebox_os.coordinator import FreeboxData, FreeboxDataUpdateCoordinator

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "00:00:5E:00:53:00"
API = "http://mafreebox.freebox.fr:80/api/v16/"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def make_data(profiles=None) -> FreeboxData:
    if profiles is None:
        profiles = {p["profile_id"]: p for p in result("network_control")}
    return FreeboxData(system=result("system"), connection=result("connection"), profiles=profiles)


class FakeEntry:
    """Entrée minimale : runtime_data et désinscription des listeners."""

    def __init__(self, data: FreeboxData) -> None:
        self.coordinator = MagicMock()
        self.coordinator.data = data
        self.coordinator.api = AsyncMock()
        self.coordinator.async_request_refresh = AsyncMock()
        self.listeners: list = []
        self.coordinator.async_add_listener = lambda cb: self.listeners.append(cb) or (lambda: None)
        self.runtime_data = MagicMock(coordinator=self.coordinator, router_device_id="router-device-id")

    def async_on_unload(self, func) -> None:
        pass


async def setup(module, entry: FakeEntry) -> list:
    added: list = []
    await module.async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return added


def profile_entities(entities: list, profile_id: int) -> dict[str, object]:
    prefix = f"{MAC}_profile_{profile_id} "
    return {e.unique_id.removeprefix(prefix): e for e in entities if e.unique_id.startswith(prefix)}


# --- Coordinateur et API -----------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_collects_profiles():
    api = AsyncMock()
    api.get_system.return_value = result("system")
    api.get_connection.return_value = result("connection")
    api.get_storage_disks.return_value = []
    api.get_storage_raids.return_value = []
    api.get_lan_interfaces.return_value = []
    api.get_call_log.return_value = []
    api.get_wifi_config.return_value = {"enabled": False}
    api.get_network_control.return_value = result("network_control")
    coordinator = FreeboxDataUpdateCoordinator(MagicMock(), MagicMock(), api)

    data = await coordinator._async_update_data()
    assert set(data.profiles) == {1, 2}

    api.get_network_control.side_effect = FreeboxPermissionError("x", "insufficient_rights")
    data = await coordinator._async_update_data()
    assert data.profiles is None
    assert "parental" in coordinator.denied_until


@pytest.mark.asyncio
async def test_update_sends_full_profile():
    # La box refuse un PUT partiel : tout le profil est renvoyé.
    profile = result("network_control")[0]
    async with aiohttp.ClientSession() as session:
        client = FreeboxApiClient(session, API, "app", "token")
        client._session_token = "s"
        with aioresponses() as m:
            m.put(f"{API}network_control/1", payload={"success": True, "result": profile})
            await client.update_network_control(profile, override=True, override_mode="denied", override_until=0)
            body = m.requests[("PUT", URL(f"{API}network_control/1"))][0].kwargs["json"]
    assert body == {
        "profile_name": "Alice",
        "profile_icon": profile["profile_icon"],
        "override_mode": "denied",
        "current_mode": "allowed",
        "override_until": 0,
        "override": True,
        "macs": profile["macs"],
        "cdayranges": [":fr_school_holidays_b"],
    }


# --- Entités -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_profile_gets_a_device_and_its_entities():
    entry = FakeEntry(make_data())
    entities = await setup(switch, entry) + await setup(sensor, entry) + await setup(button, entry)

    alice = profile_entities(entities, 1)
    assert set(alice) == {"internet_access", "access_mode", "next_change", "connected_devices", "resume_schedule"}
    device = alice["internet_access"].device_info
    assert device["name"] == "Alice"
    assert device["identifiers"] == {(DOMAIN, f"{MAC}_profile_1")}
    assert device["via_device_id"] == "router-device-id"

    assert alice["internet_access"].is_on is True
    assert alice["access_mode"].native_value == "allowed"
    assert alice["next_change"].native_value == dt_util.utc_from_timestamp(1791234000)
    assert alice["connected_devices"].native_value == 1
    assert [d["name"] for d in alice["connected_devices"].extra_state_attributes["devices"]] == ["Tab-Alice", "PC-Alice"]
    # Pas de mode manuel en cours : rien à reprendre.
    assert alice["resume_schedule"].available is False

    bob = profile_entities(entities, 2)
    assert bob["next_change"].native_value is None
    assert bob["resume_schedule"].available is True
    assert bob["internet_access"].extra_state_attributes == {
        "manual": True,
        "manual_until": None,
        "schedule_mode": "denied",
    }


@pytest.mark.asyncio
async def test_no_profile_entities_without_permission():
    entry = FakeEntry(make_data(profiles={}))
    entry.coordinator.data.profiles = None
    entry.coordinator.data.wifi = None
    assert await setup(switch, entry) == []


@pytest.mark.asyncio
async def test_new_profile_is_added_without_reload():
    data = make_data()
    entry = FakeEntry(data)
    entities = await setup(switch, entry)
    assert len(entities) == 2

    new = dict(result("network_control")[0], profile_id=3, profile_name="Chloé")
    data.profiles[3] = new
    for listener in entry.listeners:
        listener()
    assert len(entities) == 3
    assert entities[-1].device_info["name"] == "Chloé"


@pytest.mark.asyncio
async def test_removed_profile_becomes_unavailable():
    data = make_data()
    entry = FakeEntry(data)
    entities = await setup(switch, entry)
    del data.profiles[1]
    alice = profile_entities(entities, 1)["internet_access"]
    assert alice.available is False
    with pytest.raises(HomeAssistantError):
        await alice.async_turn_off()


# --- Actions -----------------------------------------------------------------


async def access_switch(profile_id: int) -> tuple[object, AsyncMock]:
    entry = FakeEntry(make_data())
    entity = profile_entities(await setup(switch, entry), profile_id)["internet_access"]
    return entity, entry.coordinator.api.update_network_control


@pytest.mark.asyncio
async def test_turn_off_blocks_until_further_notice():
    entity, update = await access_switch(1)
    await entity.async_turn_off()
    update.assert_awaited_once()
    assert update.await_args.kwargs == {"override": True, "override_mode": "denied", "override_until": 0}
    entity.coordinator.async_request_refresh.assert_awaited()


@pytest.mark.asyncio
async def test_block_for_a_duration():
    entity, update = await access_switch(1)
    before = dt_util.utcnow().timestamp()
    await entity.async_block(timedelta(hours=1))
    until = update.await_args.kwargs["override_until"]
    assert before + 3600 - 1 <= until <= dt_util.utcnow().timestamp() + 3600


@pytest.mark.asyncio
async def test_turn_on_returns_to_schedule_when_schedule_allows():
    entity, update = await access_switch(1)  # planning : autorisé
    await entity.async_turn_on()
    assert update.await_args.kwargs == {"override": False}


@pytest.mark.asyncio
async def test_turn_on_allows_until_next_change_when_schedule_blocks():
    entity, update = await access_switch(1)
    entity.profile["rule_mode"] = "denied"
    await entity.async_turn_on()
    assert update.await_args.kwargs == {"override": True, "override_mode": "allowed", "override_until": 1791234000}


@pytest.mark.asyncio
async def test_allow_for_a_duration():
    entity, update = await access_switch(1)
    await entity.async_allow(timedelta(minutes=30))
    kwargs = update.await_args.kwargs
    assert kwargs["override"] is True and kwargs["override_mode"] == "allowed"
    assert kwargs["override_until"] > dt_util.utcnow().timestamp()


@pytest.mark.asyncio
async def test_permission_error_is_explained():
    entity, update = await access_switch(1)
    update.side_effect = FreeboxPermissionError("x", "insufficient_rights")
    with pytest.raises(HomeAssistantError, match="Contrôle parental"):
        await entity.async_turn_off()


@pytest.mark.asyncio
async def test_resume_button():
    entry = FakeEntry(make_data())
    bob = profile_entities(await setup(button, entry), 2)["resume_schedule"]
    await bob.async_press()
    assert entry.coordinator.api.update_network_control.await_args.kwargs == {"override": False}


@pytest.mark.asyncio
async def test_services_target_profile_switches_only():
    entity, update = await access_switch(1)
    call = MagicMock(data={"duration": timedelta(minutes=5)})
    await services._block(entity, call)
    assert update.await_args.kwargs["override_mode"] == "denied"

    wifi = MagicMock(entity_id="switch.freebox_wi_fi")
    with pytest.raises(ServiceValidationError):
        await services._block(wifi, call)


# --- Suppression d'appareils -------------------------------------------------


@pytest.mark.asyncio
async def test_only_gone_devices_can_be_removed():
    data = make_data()
    data.disks = {1000: {"id": 1000}}
    entry = MagicMock()
    entry.runtime_data.coordinator.data = data

    def device(ident: str):
        return MagicMock(identifiers={(DOMAIN, ident)})

    assert not await async_remove_config_entry_device(MagicMock(), entry, device(MAC))
    assert not await async_remove_config_entry_device(MagicMock(), entry, device(f"{MAC}_profile_1"))
    assert not await async_remove_config_entry_device(MagicMock(), entry, device(f"{MAC}_disk_1000"))
    assert await async_remove_config_entry_device(MagicMock(), entry, device(f"{MAC}_profile_9"))


def test_translations_cover_profile_entities_and_services():
    component = Path(__file__).parent.parent / "custom_components" / "freebox_os"
    for lang in ("en", "fr"):
        tr = json.loads((component / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
        assert tr["entity"]["switch"]["internet_access"]["name"]
        assert set(tr["entity"]["sensor"]["access_mode"]["state"]) == {"allowed", "denied", "webonly"}
        for key in ("access_mode", "next_change", "connected_devices"):
            assert tr["entity"]["sensor"][key]["name"]
        assert tr["entity"]["button"]["resume_schedule"]["name"]
        assert set(tr["services"]) == {"block_internet", "allow_internet", "resume_schedule"}
        assert tr["exceptions"]["not_a_profile"]["message"]
    services_yaml = (component / "services.yaml").read_text(encoding="utf-8")
    for name in ("block_internet", "allow_internet", "resume_schedule"):
        assert f"{name}:" in services_yaml
