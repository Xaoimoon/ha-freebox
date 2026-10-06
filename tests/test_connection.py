"""Tests de l'état de la connexion : connexion Internet, dernière coupure, fibre."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.freebox_os import binary_sensor, sensor
from custom_components.freebox_os.coordinator import (
    FreeboxData,
    FreeboxDataUpdateCoordinator,
    last_outage,
)

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "00:00:5E:00:53:00"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def make_data(**overrides) -> FreeboxData:
    data = dict(
        system=result("system"),
        connection=result("connection"),
        connection_logs=result("connection_logs"),
        ftth=result("connection_ftth"),
    )
    data.update(overrides)
    return FreeboxData(**data)


async def setup(module, data: FreeboxData) -> dict:
    entry = MagicMock()
    entry.runtime_data.coordinator.data = data
    added: list = []
    await module.async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    return {e.unique_id.removeprefix(f"{MAC} "): e for e in added}


def log(id_, type_, state, date):
    return {"id": id_, "type": type_, "state": state, "date": date}


# --- Dernière coupure ---------------------------------------------------------


def test_last_outage_from_real_log():
    # Coupure de nuit vue sur la box : connexion tombée à 04:00:38, revenue à 04:02:05.
    outage = last_outage(result("connection_logs"))
    assert outage.start == dt_util.utc_from_timestamp(1787277638)
    assert outage.end == dt_util.utc_from_timestamp(1787277725)
    assert outage.duration == timedelta(seconds=87)


def test_no_outage_since_boot():
    # Le démarrage de la box (lien puis connexion qui montent) n'est pas une coupure.
    assert last_outage(result("connection_logs")[:2]) is None
    assert last_outage([]) is None


def test_ongoing_outage():
    logs = [log(1, "link", "up", 100), log(2, "conn", "up", 110), log(3, "link", "down", 500)]
    outage = last_outage(logs)
    assert outage.start == dt_util.utc_from_timestamp(500)
    assert outage.end is None and outage.duration is None


def test_latest_of_several_outages():
    logs = [
        log(1, "conn", "up", 100),
        log(2, "conn", "down", 200), log(3, "conn", "up", 260),
        log(4, "link", "down", 900), log(5, "conn", "down", 901), log(6, "link", "up", 950), log(7, "conn", "up", 990),
    ]
    outage = last_outage(logs)
    assert (outage.start, outage.duration) == (dt_util.utc_from_timestamp(900), timedelta(seconds=90))


def test_outage_ends_with_link_when_log_has_no_connection_events():
    logs = [log(1, "link", "up", 100), log(2, "link", "down", 200), log(3, "link", "up", 230)]
    assert last_outage(logs).duration == timedelta(seconds=30)


# --- Entités ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_entities():
    data = make_data()
    binaries = await setup(binary_sensor, data)
    assert binaries["connection"].is_on is True
    assert binaries["ftth_signal"].is_on is True

    sensors = await setup(sensor, data)
    outage = sensors["last_outage"]
    assert outage.native_value == dt_util.utc_from_timestamp(1787277638)
    assert outage.extra_state_attributes == {
        "end": dt_util.utc_from_timestamp(1787277725).isoformat(),
        "duration": 87,
    }
    assert sensors["sfp_pwr_rx"].native_value == -18.12
    assert sensors["sfp_pwr_tx"].native_value == 6.41
    assert sensors["sfp_pwr_rx"].native_unit_of_measurement == "dBm"

    data.connection = dict(data.connection, state="going_up")
    assert binaries["connection"].is_on is False


@pytest.mark.asyncio
async def test_firmware_update_entity():
    data = make_data(firmware_update={"state": "up_to_date"})
    update = (await setup(binary_sensor, data))["firmware_update"]
    assert update.is_on is False
    assert update.extra_state_attributes == {"update_state": "up_to_date", "installed_version": "4.12.3"}

    # États non documentés : tout ce qui n'est pas `up_to_date` est une mise à jour en attente.
    data.firmware_update = {"state": "downloading"}
    assert update.is_on is True
    assert update.extra_state_attributes["update_state"] == "downloading"

    assert "firmware_update" not in await setup(binary_sensor, make_data(firmware_update=None))


@pytest.mark.asyncio
async def test_no_fiber_entities_outside_ftth():
    data = make_data(ftth=None)
    assert "ftth_signal" not in await setup(binary_sensor, data)
    sensors = await setup(sensor, data)
    assert "sfp_pwr_rx" not in sensors and "last_outage" in sensors


@pytest.mark.asyncio
async def test_no_power_sensors_without_power_report():
    data = make_data(ftth=dict(result("connection_ftth"), sfp_has_power_report=False))
    assert "sfp_pwr_rx" not in await setup(sensor, data)


@pytest.mark.asyncio
async def test_coordinator_reads_fiber_only_on_ftth():
    api = AsyncMock()
    api.get_system.return_value = result("system")
    api.get_connection.return_value = dict(result("connection"), media="xdsl")
    api.get_connection_logs.return_value = []
    api.get_storage_disks.return_value = []
    api.get_storage_raids.return_value = []
    api.get_lan_interfaces.return_value = []
    coordinator = FreeboxDataUpdateCoordinator(MagicMock(), MagicMock(), api)
    api.get_call_log.return_value = []
    api.get_wifi_config.return_value = None
    api.get_network_control.return_value = []

    data = await coordinator._async_update_data()
    assert data.ftth is None
    api.get_connection_ftth.assert_not_called()

    api.get_connection.return_value = result("connection")
    api.get_connection_ftth.return_value = result("connection_ftth")
    data = await coordinator._async_update_data()
    assert data.ftth["sfp_pwr_rx"] == -1812
