"""Capteurs Freebox OS : connexion, débits, volumes cumulés, fibre, démarrage, ports du
switch, températures, ventilateurs, appels, disques, profils de contrôle parental."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import FreeboxConfigEntry
from .const import ACCESS_ALLOWED, ACCESS_DENIED, ACCESS_WEBONLY
from .coordinator import FreeboxData, FreeboxDataUpdateCoordinator, last_outage
from .entity import FreeboxEntity, FreeboxPortEntity, disk_device_info
from .parental import FreeboxProfileEntity, async_track_profiles


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
    # Compteurs cumulés de la box depuis son dernier démarrage : remis à zéro
    # au redémarrage, ce que `total_increasing` traite comme un nouveau cycle.
    # Utilisables tels quels par les `utility_meter` et les statistiques.
    FreeboxSensorEntityDescription(
        key="bytes_down",
        translation_key="bytes_down",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        value_fn=lambda data: data.connection["bytes_down"],
    ),
    FreeboxSensorEntityDescription(
        key="bytes_up",
        translation_key="bytes_up",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        value_fn=lambda data: data.connection["bytes_up"],
    ),
)


def _optical_power(key: str) -> Callable[[FreeboxData], float | None]:
    """Puissance optique du module SFP : la box la donne en centièmes de dBm."""

    def value(data: FreeboxData) -> float | None:
        raw = (data.ftth or {}).get(key)
        return round(raw / 100, 2) if raw is not None else None

    return value


# Fibre (FTTH), quand le module SFP remonte ses mesures. Repère GPON côté
# abonné : puissance reçue entre -8 et -27 dBm ; une baisse durable annonce
# une fibre ou une connectique qui se dégrade.
FTTH_SENSORS: tuple[FreeboxSensorEntityDescription, ...] = (
    FreeboxSensorEntityDescription(
        key="sfp_pwr_rx",
        translation_key="sfp_pwr_rx",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_optical_power("sfp_pwr_rx"),
    ),
    FreeboxSensorEntityDescription(
        key="sfp_pwr_tx",
        translation_key="sfp_pwr_tx",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_optical_power("sfp_pwr_tx"),
    ),
)


# Compteurs d'octets d'un port, vus de la box : « reçues » = envoyées par
# l'appareil branché sur le port.
PORT_BYTES = {"rx": "rx_good_bytes", "tx": "tx_bytes"}

# Écart à partir duquel l'heure de démarrage recalculée signale un redémarrage
# (sinon : simple gigue d'une seconde entre l'uptime et l'horloge de HA).
BOOT_TIME_TOLERANCE = timedelta(minutes=1)


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
    entities.append(FreeboxLastOutageSensor(coordinator))
    entities.append(FreeboxBootTimeSensor(coordinator))
    for port in data.switch_ports.values():
        entities.append(FreeboxPortSpeedSensor(coordinator, port))
        entities.extend(FreeboxPortBytesSensor(coordinator, port, key) for key in PORT_BYTES)
    if data.ftth and data.ftth.get("sfp_has_power_report"):
        entities.extend(FreeboxSensor(coordinator, description) for description in FTTH_SENSORS)

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

    async_track_profiles(
        entry,
        coordinator,
        async_add_entities,
        lambda device_id, profile: [
            FreeboxProfileModeSensor(coordinator, device_id, profile),
            FreeboxProfileNextChangeSensor(coordinator, device_id, profile),
            FreeboxProfileDevicesSensor(coordinator, device_id, profile),
        ],
    )


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


class FreeboxLastOutageSensor(FreeboxEntity, SensorEntity):
    """Début de la dernière coupure de la connexion depuis le démarrage de la box ;
    inconnu s'il n'y en a pas eu. Fin et durée en attributs."""

    _attr_translation_key = "last_outage"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "last_outage")

    @property
    def native_value(self):
        outage = last_outage(self.coordinator.data.connection_logs)
        return outage.start if outage else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        outage = last_outage(self.coordinator.data.connection_logs)
        if outage is None:
            return {}
        return {
            "end": outage.end.isoformat() if outage.end else None,
            "duration": int(outage.duration.total_seconds()) if outage.duration else None,
        }


class FreeboxBootTimeSensor(FreeboxEntity, SensorEntity):
    """Heure du dernier démarrage de la box, déduite de son uptime."""

    _attr_translation_key = "boot_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "boot_time")
        self._boot_time: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        uptime = self.coordinator.data.system.get("uptime_val")
        if uptime is None:
            return None
        boot = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(microsecond=0)
        # Garde la valeur précédente tant que l'écart n'est que de la gigue.
        if self._boot_time is None or abs(boot - self._boot_time) > BOOT_TIME_TOLERANCE:
            self._boot_time = boot
        return self._boot_time


class FreeboxPortSpeedSensor(FreeboxPortEntity, SensorEntity):
    """Vitesse négociée d'un port ; inconnue quand rien n'y est branché."""

    _attr_translation_key = "port_speed"
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, port: dict[str, Any]) -> None:
        super().__init__(coordinator, port, "speed")

    @property
    def native_value(self) -> int | None:
        if not self.link_up:
            return None
        try:
            return int((self.port or {}).get("speed"))
        except (TypeError, ValueError):
            return None


class FreeboxPortBytesSensor(FreeboxPortEntity, SensorEntity):
    """Octets reçus ou envoyés par la box sur un port, depuis son démarrage."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, port: dict[str, Any], direction: str) -> None:
        super().__init__(coordinator, port, f"bytes_{direction}")
        self._attr_translation_key = f"port_bytes_{direction}"
        self._stat = PORT_BYTES[direction]

    @property
    def native_value(self) -> int | None:
        return self.port_stats.get(self._stat)


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


class FreeboxProfileModeSensor(FreeboxProfileEntity, SensorEntity):
    """Mode d'accès en vigueur : autorisé, bloqué (ou l'ancien « web seulement »)."""

    _attr_translation_key = "access_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [ACCESS_ALLOWED, ACCESS_DENIED, ACCESS_WEBONLY]

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, router_device_id: str, profile: dict[str, Any]) -> None:
        super().__init__(coordinator, router_device_id, profile, "access_mode")

    @property
    def native_value(self) -> str | None:
        mode = (self.profile or {}).get("current_mode")
        return mode if mode in self._attr_options else None


class FreeboxProfileNextChangeSensor(FreeboxProfileEntity, SensorEntity):
    """Prochain changement de mode : fin d'une pause, début du prochain blocage
    prévu… Inconnu quand rien n'est prévu."""

    _attr_translation_key = "next_change"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, router_device_id: str, profile: dict[str, Any]) -> None:
        super().__init__(coordinator, router_device_id, profile, "next_change")

    @property
    def native_value(self):
        next_change = (self.profile or {}).get("next_change") or 0
        return dt_util.utc_from_timestamp(next_change) if next_change else None


class FreeboxProfileDevicesSensor(FreeboxProfileEntity, SensorEntity):
    """Nombre d'appareils du profil connectés en ce moment ; la liste complète
    est en attribut."""

    _attr_translation_key = "connected_devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, router_device_id: str, profile: dict[str, Any]) -> None:
        super().__init__(coordinator, router_device_id, profile, "connected_devices")

    def _hosts(self) -> list[dict[str, Any]]:
        return (self.profile or {}).get("hosts") or []

    @property
    def native_value(self) -> int:
        return sum(1 for host in self._hosts() if host.get("active"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "devices": [
                {
                    "name": (host.get("primary_name") or "").strip() or host["l2ident"]["id"],
                    "mac": host["l2ident"]["id"],
                    "connected": bool(host.get("active")),
                }
                for host in self._hosts()
            ]
        }
