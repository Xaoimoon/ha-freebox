"""Suivi de présence des appareils du LAN, et de la box elle-même.

Comme pour tout `ScannerEntity`, le suivi d'un appareil n'est activé par
défaut que si Home Assistant connaît déjà un appareil avec cette MAC (la box
elle-même, par exemple) : les ~130 hôtes du LAN arrivent désactivés.

Depuis HA 2026.9, un `ScannerEntity` dont la MAC est connue (ré)enregistre
l'appareil qui porte cette MAC sous le nom `hostname or mac_address` : sans
`hostname`, l'appareil de la box prendrait sa MAC pour nom.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import FreeboxConfigEntry
from .coordinator import FreeboxDataUpdateCoordinator

DEFAULT_DEVICE_NAME = "Unknown device"

DEVICE_ICONS = {
    "freebox_delta": "mdi:television-guide",
    "freebox_hd": "mdi:television-guide",
    "freebox_mini": "mdi:television-guide",
    "freebox_player": "mdi:television-guide",
    "ip_camera": "mdi:cctv",
    "ip_phone": "mdi:phone-voip",
    "laptop": "mdi:laptop",
    "multimedia_device": "mdi:play-network",
    "nas": "mdi:nas",
    "networking_device": "mdi:network",
    "printer": "mdi:printer",
    "router": "mdi:router-wireless",
    "smartphone": "mdi:cellphone",
    "tablet": "mdi:tablet",
    "television": "mdi:television",
    "vg_console": "mdi:gamepad-variant",
    "workstation": "mdi:desktop-tower-monitor",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    router_mac = coordinator.data.system["mac"]
    async_add_entities([FreeboxRouterTracker(coordinator)])

    tracked: set[str] = {router_mac}

    @callback
    def add_new_hosts() -> None:
        new = [
            FreeboxHostTracker(coordinator, mac)
            for mac in coordinator.data.hosts
            if mac not in tracked
        ]
        tracked.update(entity.mac_address for entity in new)
        if new:
            async_add_entities(new)

    add_new_hosts()
    entry.async_on_unload(coordinator.async_add_listener(add_new_hosts))


class FreeboxHostTracker(CoordinatorEntity[FreeboxDataUpdateCoordinator], ScannerEntity):
    """Un appareil vu par le navigateur LAN de la box."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        host = coordinator.data.hosts[mac]
        self._attr_mac_address = mac
        self._attr_name = (host.get("primary_name") or "").strip() or DEFAULT_DEVICE_NAME
        self._attr_hostname = self._attr_name
        self._attr_icon = DEVICE_ICONS.get(host.get("host_type"), "mdi:help-network")

    @property
    def _host(self) -> dict[str, Any]:
        return self.coordinator.data.hosts.get(self.mac_address, {})

    @property
    def is_connected(self) -> bool:
        return bool(self._host.get("active"))

    @property
    def ip_address(self) -> str | None:
        return next(
            (
                l3["addr"]
                for l3 in self._host.get("l3connectivities") or []
                if l3.get("af") == "ipv4" and l3.get("active")
            ),
            None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        host = self._host
        attrs: dict[str, Any] = {}
        if host.get("last_time_reachable"):
            attrs["last_time_reachable"] = datetime.fromtimestamp(host["last_time_reachable"])
        if host.get("last_activity"):
            attrs["last_time_activity"] = datetime.fromtimestamp(host["last_activity"])
        return attrs


class FreeboxRouterTracker(CoordinatorEntity[FreeboxDataUpdateCoordinator], ScannerEntity):
    """La box elle-même, toujours présente, avec l'état de la connexion en attributs."""

    _attr_has_entity_name = True
    _attr_icon = DEVICE_ICONS["router"]

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        system = coordinator.data.system
        self._attr_mac_address = system["mac"]
        self._attr_name = (system.get("model_info") or {}).get("pretty_name") or "Freebox"
        # Le même nom que l'appareil de la box (voir l'en-tête du module).
        self._attr_hostname = self._attr_name

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        system = self.coordinator.data.system
        connection = self.coordinator.data.connection
        # Arrondi à la minute : sinon l'attribut bouge à chaque relevé.
        boot = dt_util.utcnow() - timedelta(seconds=system["uptime_val"])
        return {
            "IPv4": connection.get("ipv4"),
            "IPv6": connection.get("ipv6"),
            "connection_type": connection.get("media"),
            "uptime": boot.replace(second=0, microsecond=0),
            "firmware_version": system.get("firmware_version"),
            "serial": system.get("serial"),
        }
