"""Capteurs Freebox OS : débits, températures, ventilateurs, appels, disques."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import FreeboxConfigEntry
from .coordinator import FreeboxData, FreeboxDataUpdateCoordinator
from .entity import FreeboxEntity, disk_device_info


@dataclass(frozen=True, kw_only=True)
class FreeboxSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[FreeboxData], Any]


CONNECTION_SENSORS: tuple[FreeboxSensorEntityDescription, ...] = (
    FreeboxSensorEntityDescription(
        key="rate_down",
        translation_key="rate_down",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        # La box donne des octets/s.
        value_fn=lambda data: round(data.connection["rate_down"] / 1000, 2),
    ),
    FreeboxSensorEntityDescription(
        key="rate_up",
        translation_key="rate_up",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.KILOBYTES_PER_SECOND,
        value_fn=lambda data: round(data.connection["rate_up"] / 1000, 2),
    ),
)


def _new_calls(data: FreeboxData, call_type: str) -> list[dict[str, Any]]:
    return [call for call in data.calls or [] if call.get("new") and call.get("type") == call_type]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    entities: list[SensorEntity] = [
        FreeboxSensor(coordinator, description) for description in CONNECTION_SENSORS
    ]

    # Les identifiants et les noms des capteurs varient selon le modèle : on
    # prend ceux que la box annonce (déjà traduits par Freebox OS).
    entities.extend(
        FreeboxSystemSensor(
            coordinator,
            "sensors",
            sensor,
            SensorEntityDescription(
                key=sensor["id"],
                name=sensor["name"],
                device_class=SensorDeviceClass.TEMPERATURE,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )
        for sensor in data.system.get("sensors") or []
    )
    entities.extend(
        FreeboxSystemSensor(
            coordinator,
            "fans",
            fan,
            SensorEntityDescription(
                key=fan["id"],
                name=fan["name"],
                translation_key="fan_speed",
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )
        for fan in data.system.get("fans") or []
    )

    if data.calls is not None:
        entities.append(FreeboxMissedCallsSensor(coordinator))

    entities.extend(
        FreeboxPartitionSensor(coordinator, entry.runtime_data.router_device_id, disk, partition)
        for disk in data.disks.values()
        for partition in disk.get("partitions") or []
    )

    async_add_entities(entities)


class FreeboxSensor(FreeboxEntity, SensorEntity):
    entity_description: FreeboxSensorEntityDescription

    def __init__(
        self, coordinator: FreeboxDataUpdateCoordinator, description: FreeboxSensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class FreeboxSystemSensor(FreeboxEntity, SensorEntity):
    """Température ou ventilateur listé par `system/` (`sensors` / `fans`)."""

    def __init__(
        self,
        coordinator: FreeboxDataUpdateCoordinator,
        group: str,
        item: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._group = group
        self._id = item["id"]

    def _item(self) -> dict[str, Any] | None:
        return next(
            (i for i in self.coordinator.data.system.get(self._group) or [] if i["id"] == self._id),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._item() is not None

    @property
    def native_value(self) -> Any:
        item = self._item()
        return item.get("value") if item else None


class FreeboxMissedCallsSensor(FreeboxEntity, SensorEntity):
    _attr_translation_key = "missed"
    _attr_native_unit_of_measurement = "calls"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "missed")

    @property
    def native_value(self) -> int:
        return len(_new_calls(self.coordinator.data, "missed"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            dt_util.utc_from_timestamp(call["datetime"]).isoformat(): call.get("name")
            for call in _new_calls(self.coordinator.data, "missed")
        }


class FreeboxPartitionSensor(FreeboxEntity, SensorEntity):
    """Espace libre d'une partition, sur l'appareil du disque."""

    _attr_translation_key = "partition_free_space"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: FreeboxDataUpdateCoordinator,
        router_device_id: str,
        disk: dict[str, Any],
        partition: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, f"partition_free_space {disk['id']} {partition['id']}")
        self._disk_id = disk["id"]
        self._partition_id = partition["id"]
        self._attr_translation_placeholders = {"partition": partition.get("label") or str(partition["id"])}
        self._attr_device_info = disk_device_info(self._router_mac, router_device_id, disk)

    def _partition(self) -> dict[str, Any] | None:
        disk = self.coordinator.data.disks.get(self._disk_id) or {}
        return next((p for p in disk.get("partitions") or [] if p["id"] == self._partition_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._partition() is not None

    @property
    def native_value(self) -> float | None:
        partition = self._partition()
        if not partition or not partition.get("total_bytes"):
            return None
        return round(partition["free_bytes"] * 100 / partition["total_bytes"], 2)
