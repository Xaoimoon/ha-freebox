"""Intégration Freebox OS pour Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    FreeboxApiClient,
    FreeboxAuthError,
    FreeboxConnectionError,
    async_get_api_version,
    build_api_url,
)
from .const import APP_ID, CONF_APP_TOKEN, DOMAIN  # noqa: F401
from .coordinator import FreeboxDataUpdateCoordinator
from .entity import router_device_info

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class FreeboxRuntimeData:
    api: FreeboxApiClient
    coordinator: FreeboxDataUpdateCoordinator
    # Id de l'appareil box dans le registre, auquel les disques se rattachent.
    router_device_id: str


type FreeboxConfigEntry = ConfigEntry[FreeboxRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FreeboxConfigEntry) -> bool:
    """Configure une Freebox à partir d'une entrée de configuration."""
    session = async_get_clientsession(hass)
    host, port = entry.data[CONF_HOST], entry.data[CONF_PORT]
    # Relu à chaque démarrage : le préfixe versionné suit les mises à jour de Freebox OS.
    try:
        api_info = await async_get_api_version(session, host, port)
    except FreeboxConnectionError as err:
        raise ConfigEntryNotReady(f"Freebox injoignable : {err}") from err

    api = FreeboxApiClient(session, build_api_url(host, port, api_info), APP_ID, entry.data[CONF_APP_TOKEN])
    try:
        await api.open_session()
    except FreeboxAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except FreeboxConnectionError as err:
        raise ConfigEntryNotReady(f"Freebox injoignable : {err}") from err

    coordinator = FreeboxDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    # Enregistré avant les plateformes : le disque s'y rattache (via_device_id).
    router = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **router_device_info(coordinator.data.system, f"http://{host}:{port}/"),
    )

    entry.runtime_data = FreeboxRuntimeData(
        api=api, coordinator=coordinator, router_device_id=router.id
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FreeboxConfigEntry) -> bool:
    """Décharge une entrée de configuration."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.api.close_session()
    return unloaded
