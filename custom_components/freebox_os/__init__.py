"""Intégration Freebox OS pour Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

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
from .parental import profile_identifier
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Enregistre les actions du contrôle parental (une fois pour toutes les box)."""
    async_setup_services(hass)
    return True


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


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: FreeboxConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Autorise la suppression d'un appareil disparu de la box (profil supprimé
    dans Freebox OS, disque retiré) ; la box elle-même et ce qui existe encore
    reviendraient de toute façon.
    """
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return False
    data = runtime_data.coordinator.data
    mac = data.system["mac"]
    live = {mac}
    live |= {profile_identifier(mac, profile_id) for profile_id in data.profiles or {}}
    live |= {f"{mac}_disk_{disk_id}" for disk_id in data.disks}
    return not any(domain == DOMAIN and ident in live for domain, ident in device_entry.identifiers)
