"""Capteurs binaires Freebox OS : connexion Internet, signal fibre."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeboxConfigEntry
from .coordinator import FreeboxData, FreeboxDataUpdateCoordinator
from .entity import FreeboxEntity


@dataclass(frozen=True, kw_only=True)
class FreeboxBinarySensorEntityDescription(BinarySensorEntityDescription):
    value_fn: Callable[[FreeboxData], bool | None]
    exists_fn: Callable[[FreeboxData], bool] = lambda data: True


BINARY_SENSORS: tuple[FreeboxBinarySensorEntityDescription, ...] = (
    FreeboxBinarySensorEntityDescription(
        key="connection",
        translation_key="connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        # `going_up` / `going_down` comptent comme hors ligne.
        value_fn=lambda data: data.connection.get("state") == "up",
    ),
    FreeboxBinarySensorEntityDescription(
        key="ftth_signal",
        translation_key="ftth_signal",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: bool(data.ftth.get("sfp_has_signal")) if data.ftth else None,
        exists_fn=lambda data: data.ftth is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        FreeboxBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if description.exists_fn(coordinator.data)
    )


class FreeboxBinarySensor(FreeboxEntity, BinarySensorEntity):
    entity_description: FreeboxBinarySensorEntityDescription

    def __init__(
        self, coordinator: FreeboxDataUpdateCoordinator, description: FreeboxBinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
