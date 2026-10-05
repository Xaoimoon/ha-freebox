"""Appareils et entité de base de l'intégration Freebox OS.

Comme l'intégration officielle : un appareil pour la box (identifié par sa
MAC), plus un appareil par disque, rattaché à la box (`via_device_id`).
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FreeboxDataUpdateCoordinator

MANUFACTURER = "Freebox SAS"


def router_device_info(system: dict[str, Any], configuration_url: str) -> DeviceInfo:
    model_info = system.get("model_info") or {}
    return DeviceInfo(
        configuration_url=configuration_url,
        connections={(CONNECTION_NETWORK_MAC, system["mac"])},
        identifiers={(DOMAIN, system["mac"])},
        manufacturer=MANUFACTURER,
        name=model_info.get("pretty_name"),
        model=model_info.get("pretty_name"),
        model_id=model_info.get("name"),
        sw_version=system.get("firmware_version"),
        hw_version=system.get("board_name"),
        serial_number=system.get("serial"),
    )


def disk_device_info(router_mac: str, router_device_id: str, disk: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{router_mac}_disk_{disk['id']}")},
        name=f"Disk {disk['id']}",
        model=disk.get("model"),
        sw_version=disk.get("firmware"),
        via_device_id=router_device_id,
    )


class FreeboxEntity(CoordinatorEntity[FreeboxDataUpdateCoordinator]):
    """Entité rattachée à l'appareil de la box."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._router_mac: str = coordinator.data.system["mac"]
        self._attr_unique_id = f"{self._router_mac} {key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._router_mac)})


class FreeboxPortEntity(FreeboxEntity):
    """Entité d'un port du switch de la box, nommée d'après le port (« Ethernet 2 »)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, port: dict[str, Any], key: str) -> None:
        super().__init__(coordinator, f"port_{port['id']}_{key}")
        self._port_id: int = port["id"]
        self._attr_translation_placeholders = {"port": port.get("name") or f"Port {port['id']}"}

    @property
    def port(self) -> dict[str, Any] | None:
        return self.coordinator.data.switch_ports.get(self._port_id)

    @property
    def port_stats(self) -> dict[str, Any]:
        return self.coordinator.data.port_stats.get(self._port_id) or {}

    @property
    def link_up(self) -> bool:
        return (self.port or {}).get("link") == "up"

    @property
    def available(self) -> bool:
        return super().available and self.port is not None
