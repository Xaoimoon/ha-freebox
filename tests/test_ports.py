"""Tests des ports du switch et de l'heure de démarrage de la box."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.freebox_os import binary_sensor, sensor
from custom_components.freebox_os.coordinator import FreeboxData, FreeboxDataUpdateCoordinator

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "00:00:5E:00:53:00"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def make_data() -> FreeboxData:
    ports = {p["id"]: p for p in result("switch_status")}
    stats = {port_id: {} for port_id in ports}
    stats[2] = result("switch_port_stats")
    return FreeboxData(
        system=result("system"), connection=result("connection"), switch_ports=ports, port_stats=stats
    )


async def setup(module, data: FreeboxData) -> dict:
    entry = MagicMock()
    entry.runtime_data.coordinator.data = data
    added: list = []
    await module.async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return {e.unique_id.removeprefix(f"{MAC} "): e for e in added}


@pytest.mark.asyncio
async def test_port_entities():
    data = make_data()
    links = await setup(binary_sensor, data)
    sensors = await setup(sensor, data)

    # Ethernet 1 à 4 et le port SFP LAN (id 9999).
    assert {k for k in links if k.startswith("port_")} == {f"port_{i}_link" for i in (1, 2, 3, 4, 9999)}
    for port_id in (1, 2, 3, 4, 9999):
        for key in ("speed", "bytes_rx", "bytes_tx"):
            assert f"port_{port_id}_{key}" in sensors

    eth2 = links["port_2_link"]
    assert eth2.is_on is True
    assert eth2.translation_placeholders == {"port": "Ethernet 2"}
    assert eth2.extra_state_attributes == {
        "mode": "1000BaseT-FD", "duplex": "full", "rx_errors": 0, "rx_fcs_errors": 0,
    }
    assert sensors["port_2_speed"].native_value == 1000
    assert sensors["port_4_speed"].native_value == 2500
    assert sensors["port_2_bytes_rx"].native_value == 41918039679
    assert sensors["port_2_bytes_tx"].native_value == 880750565127
    assert sensors["port_2_bytes_rx"].state_class == "total_increasing"

    # Port libre : la box annonce « 10 half », c'est trompeur.
    eth1 = links["port_1_link"]
    assert eth1.is_on is False
    assert eth1.extra_state_attributes["mode"] is None
    assert sensors["port_1_speed"].native_value is None


@pytest.mark.asyncio
async def test_coordinator_reads_stats_of_each_port():
    api = AsyncMock()
    api.get_system.return_value = result("system")
    api.get_connection.return_value = dict(result("connection"), media="ethernet")
    api.get_connection_logs.return_value = []
    api.get_switch_status.return_value = result("switch_status")
    api.get_switch_port_stats.return_value = result("switch_port_stats")
    api.get_storage_disks.return_value = []
    api.get_storage_raids.return_value = []
    api.get_lan_interfaces.return_value = []
    coordinator = FreeboxDataUpdateCoordinator(MagicMock(), MagicMock(), api)
    coordinator.supports_calls = coordinator.supports_wifi = coordinator.supports_profiles = False

    data = await coordinator._async_update_data()
    assert set(data.port_stats) == {1, 2, 3, 4, 9999}
    assert sorted(c.args[0] for c in api.get_switch_port_stats.await_args_list) == [1, 2, 3, 4, 9999]


@pytest.mark.asyncio
async def test_boot_time_ignores_jitter_and_follows_reboots():
    data = make_data()
    boot = (await setup(sensor, data))["boot_time"]
    now = dt_util.parse_datetime("2026-10-05T21:00:00+00:00")
    uptime = data.system["uptime_val"]

    with patch("custom_components.freebox_os.sensor.dt_util.utcnow", return_value=now):
        first = boot.native_value
    assert first == now - timedelta(seconds=uptime)

    # 30 s plus tard, l'uptime a avancé de 29 s : même heure de démarrage.
    data.system = dict(data.system, uptime_val=uptime + 29)
    with patch("custom_components.freebox_os.sensor.dt_util.utcnow", return_value=now + timedelta(seconds=30)):
        assert boot.native_value == first

    # Redémarrage : uptime de 2 minutes.
    data.system = dict(data.system, uptime_val=120)
    later = now + timedelta(hours=1)
    with patch("custom_components.freebox_os.sensor.dt_util.utcnow", return_value=later):
        assert boot.native_value == later - timedelta(seconds=120)
