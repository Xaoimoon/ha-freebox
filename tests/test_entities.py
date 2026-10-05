"""Tests des entités : valeurs, appareils et identifiants, calqués sur l'intégration officielle."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.freebox_os import button, sensor, switch
from custom_components.freebox_os.const import DOMAIN
from custom_components.freebox_os.coordinator import FreeboxData
from custom_components.freebox_os.device_tracker import FreeboxHostTracker, FreeboxRouterTracker
from custom_components.freebox_os.entity import router_device_info

FIXTURES = Path(__file__).parent / "fixtures"
COMPONENT = Path(__file__).parent.parent / "custom_components" / "freebox_os"
MAC = "00:00:5E:00:53:00"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def make_data(**overrides) -> FreeboxData:
    hosts = {h["l2ident"]["id"]: h for h in result("lan_browser_pub")}
    data = dict(
        system=result("system"),
        connection=result("connection"),
        hosts=hosts,
        disks={d["id"]: d for d in result("storage_disk")},
        calls=result("call_log"),
        wifi=result("wifi_config"),
    )
    data.update(overrides)
    return FreeboxData(**data)


def make_coordinator(data: FreeboxData) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.api = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


async def setup_platform(module, data: FreeboxData) -> list:
    entry = MagicMock()
    entry.runtime_data.coordinator = make_coordinator(data)
    entry.runtime_data.router_device_id = "router-device-id"
    added: list = []
    await module.async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return added


def test_router_device_info():
    info = router_device_info(result("system"), "http://mafreebox.freebox.fr:80/")
    assert info["identifiers"] == {(DOMAIN, MAC)}
    assert info["manufacturer"] == "Freebox SAS"
    assert info["name"] == info["model"] == "Freebox v9 (r1)"
    assert info["model_id"] == "fbxgw9-r1"
    assert info["hw_version"] == "fbxgw9r"
    assert info["sw_version"] == "4.12.3"


@pytest.mark.asyncio
async def test_sensors_match_core_integration():
    entities = await setup_platform(sensor, make_data())
    by_id = {e.unique_id: e for e in entities}

    # Débits en ko/s, comme l'intégration officielle.
    assert by_id[f"{MAC} rate_down"].native_value == 425.01
    assert by_id[f"{MAC} rate_up"].native_value == 9.57
    # Volumes cumulés : octets bruts de la box, affichés en Go.
    bytes_down = by_id[f"{MAC} bytes_down"]
    assert bytes_down.native_value == 6081198020471
    assert bytes_down.state_class == "total_increasing"
    assert bytes_down.native_unit_of_measurement == "B"
    assert by_id[f"{MAC} bytes_up"].native_value == 463495916561
    # Températures et ventilateur, noms fournis par la box.
    cpu0 = by_id[f"{MAC} temp_cpu0"]
    assert cpu0.native_value == 57
    assert cpu0.entity_description.name == "Température CPU 0"
    assert by_id[f"{MAC} fan0_speed"].native_value == 0
    assert by_id[f"{MAC} missed"].native_value == 1
    nas = by_id[f"{MAC} partition_free_space 1000 {result('storage_disk')[0]['partitions'][0]['id']}"]
    assert nas.translation_placeholders == {"partition": "Nas"}
    assert nas.native_value == 88.27
    assert nas.device_info["name"] == "Disk 1000"
    assert nas.device_info["via_device_id"] == "router-device-id"


@pytest.mark.asyncio
async def test_optional_entities_skipped_without_permission():
    data = make_data(calls=None, wifi=None)
    assert not [e for e in await setup_platform(sensor, data) if e.unique_id.endswith("missed")]
    assert [e.unique_id for e in await setup_platform(button, data)] == [f"{MAC} reboot"]
    assert await setup_platform(switch, data) == []


@pytest.mark.asyncio
async def test_wifi_switch():
    (wifi,) = await setup_platform(switch, make_data())
    assert wifi.is_on is False
    await wifi.async_turn_on()
    wifi.coordinator.api.set_wifi_enabled.assert_awaited_once_with(True)


@pytest.mark.asyncio
async def test_buttons():
    reboot, mark = await setup_platform(button, make_data())
    await reboot.async_press()
    reboot.coordinator.api.reboot.assert_awaited_once()
    await mark.async_press()
    mark.coordinator.api.mark_calls_as_read.assert_awaited_once()


def test_host_tracker():
    coordinator = make_coordinator(make_data())
    nas = FreeboxHostTracker(coordinator, "00:00:5E:00:53:10")
    phone = FreeboxHostTracker(coordinator, "00:00:5E:00:53:11")
    unnamed = FreeboxHostTracker(coordinator, "00:00:5E:00:53:12")
    assert nas.unique_id == "00:00:5E:00:53:10"
    assert nas.is_connected and nas.ip_address == "192.168.1.10" and nas.icon == "mdi:nas"
    assert not phone.is_connected and phone.ip_address is None
    assert unnamed.name == "Unknown device" and unnamed.icon == "mdi:help-network"


def test_router_tracker():
    router = FreeboxRouterTracker(make_coordinator(make_data()))
    assert router.unique_id == MAC
    assert router.name == "Freebox v9 (r1)"
    # Sinon HA ≥ 2026.9 renomme l'appareil de la box avec sa MAC.
    assert router.hostname == "Freebox v9 (r1)"
    assert router.is_connected
    attrs = router.extra_state_attributes
    assert attrs["connection_type"] == "ftth"
    assert attrs["firmware_version"] == "4.12.3"


def _keys(tree: dict, prefix: str = "") -> set[str]:
    out = set()
    for key, value in tree.items():
        path = f"{prefix}{key}"
        out |= _keys(value, path + ".") if isinstance(value, dict) else {path}
    return out


def test_translations_cover_entities_and_match():
    en = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((COMPONENT / "translations" / "fr.json").read_text(encoding="utf-8"))
    assert _keys(en) == _keys(fr)
    for platform, key in [
        ("sensor", "rate_down"),
        ("sensor", "rate_up"),
        ("sensor", "bytes_down"),
        ("sensor", "bytes_up"),
        ("sensor", "missed"),
        ("sensor", "partition_free_space"),
        ("button", "mark_calls_as_read"),
        ("switch", "wifi"),
    ]:
        assert en["entity"][platform][key]["name"]
