"""Coordinateur de l'intégration Freebox OS : un relevé complet toutes les 30 s."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    FreeboxApiClient,
    FreeboxApiError,
    FreeboxAuthError,
    FreeboxPermissionError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


@dataclass
class FreeboxData:
    """Instantané de l'état de la box."""

    system: dict[str, Any]
    connection: dict[str, Any]
    # Journal de connexion depuis le démarrage de la box.
    connection_logs: list[dict[str, Any]] = field(default_factory=list)
    # Module SFP fibre ; None hors FTTH.
    ftth: dict[str, Any] | None = None
    # Appareils du LAN, toutes interfaces confondues, par adresse MAC.
    hosts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Disques par id, partitions comprises.
    disks: dict[int, dict[str, Any]] = field(default_factory=dict)
    raids: dict[int, dict[str, Any]] = field(default_factory=dict)
    # None quand l'application n'a pas le droit `calls` / `settings`.
    calls: list[dict[str, Any]] | None = None
    wifi: dict[str, Any] | None = None
    # Profils de contrôle parental par profile_id ; None sans le droit `parental`.
    profiles: dict[int, dict[str, Any]] | None = None


class FreeboxDataUpdateCoordinator(DataUpdateCoordinator[FreeboxData]):
    """Interroge l'API locale de la Freebox."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, api: FreeboxApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        # Désactivés pour la session HA au premier refus : inutile de
        # redemander toutes les 30 s ce que la box ne fournira pas.
        self.supports_hosts = True
        self.supports_calls = True
        self.supports_wifi = True
        self.supports_profiles = True

    async def _async_update_data(self) -> FreeboxData:
        try:
            data = FreeboxData(
                system=await self.api.get_system(),
                connection=await self.api.get_connection(),
            )
            data.connection_logs = await self.api.get_connection_logs()
            if data.connection.get("media") == "ftth":
                data.ftth = await self.api.get_connection_ftth()
            data.disks = {disk["id"]: disk for disk in await self.api.get_storage_disks()}
            data.raids = {raid["id"]: raid for raid in await self.api.get_storage_raids()}
            if self.supports_hosts:
                data.hosts = await self._fetch_hosts()
            if self.supports_calls:
                data.calls = await self._optional(self.api.get_call_log, "supports_calls", "calls")
            if self.supports_wifi:
                data.wifi = await self._optional(self.api.get_wifi_config, "supports_wifi", "settings")
            if self.supports_profiles:
                profiles = await self._optional(self.api.get_network_control, "supports_profiles", "parental")
                if profiles is not None:
                    data.profiles = {p["profile_id"]: p for p in profiles}
        except FreeboxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FreeboxApiError as err:
            raise UpdateFailed(str(err)) from err
        return data

    async def _optional(self, fetch, flag: str, permission: str) -> Any:
        """Lecture soumise à un droit de l'application : None si refusée."""
        try:
            return await fetch()
        except FreeboxPermissionError:
            _LOGGER.warning(
                "Droit « %s » non accordé à l'application dans Freebox OS : entités désactivées", permission
            )
            setattr(self, flag, False)
            return None

    async def _fetch_hosts(self) -> dict[str, dict[str, Any]]:
        hosts: dict[str, dict[str, Any]] = {}
        try:
            for interface in await self.api.get_lan_interfaces():
                if not interface.get("host_count"):
                    continue
                for host in await self.api.get_lan_hosts(interface["name"]):
                    mac = (host.get("l2ident") or {}).get("id")
                    if mac:
                        hosts[mac] = host
        except FreeboxApiError as err:
            # En mode bridge, la box n'a pas de liste d'hôtes.
            if err.error_code != "nodev":
                raise
            _LOGGER.debug("Liste des appareils indisponible (mode bridge)")
            self.supports_hosts = False
        return hosts


@dataclass(frozen=True)
class Outage:
    """Coupure de la connexion Internet relevée dans le journal de la box."""

    start: datetime
    # None tant que la connexion n'est pas revenue.
    end: datetime | None

    @property
    def duration(self) -> timedelta | None:
        return self.end - self.start if self.end else None


def last_outage(logs: list[dict[str, Any]]) -> Outage | None:
    """Dernière coupure du journal de connexion (depuis le démarrage de la box).

    Une coupure commence au premier événement `down` (lien fibre ou connexion
    IP) et se termine quand la connexion IP repasse `up` (le lien, si le
    journal ne contient pas d'événements de connexion).
    """
    events = sorted(logs, key=lambda log: (log.get("date", 0), log.get("id", 0)))
    restore_type = "conn" if any(e.get("type") == "conn" for e in events) else "link"
    outage: Outage | None = None
    start: int | None = None
    for event in events:
        state = event.get("state")
        if state == "down" and start is None:
            start = event["date"]
            outage = Outage(dt_util.utc_from_timestamp(start), None)
        elif state == "up" and start is not None and event.get("type") == restore_type:
            outage = Outage(dt_util.utc_from_timestamp(start), dt_util.utc_from_timestamp(event["date"]))
            start = None
    return outage
