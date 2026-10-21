"""Mise à jour du firmware Freebox OS : version installée sur la box, dernière
version annoncée par Free sur son blog.

Pas d'installation depuis Home Assistant : la box ne s'installe la nouvelle
version qu'en redémarrant, ce qui coupe Internet et le NAS.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeboxConfigEntry
from .coordinator import FreeboxDataUpdateCoordinator
from .entity import FreeboxEntity
from .releases import FreeboxRelease, FreeboxReleasesCoordinator, latest_release, model_name, version_key

# Longueur maximale de `release_summary` acceptée par Home Assistant.
SUMMARY_MAX_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime_data = entry.runtime_data
    async_add_entities([FreeboxFirmwareUpdate(runtime_data.coordinator, runtime_data.releases)])


class FreeboxFirmwareUpdate(FreeboxEntity, UpdateEntity):
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, releases: FreeboxReleasesCoordinator) -> None:
        super().__init__(coordinator, "firmware")
        self.releases = releases

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.releases.async_add_listener(self._handle_coordinator_update))

    @property
    def release(self) -> FreeboxRelease | None:
        model = model_name((self.coordinator.data.system.get("model_info") or {}).get("name"))
        return latest_release(self.releases.data or [], model)

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.data.system.get("firmware_version")

    @property
    def latest_version(self) -> str | None:
        installed, release = self.installed_version, self.release
        # Flux pas encore lu, ou box en avance sur le blog (bêta) : rien à proposer.
        if release is None or (installed and version_key(installed) >= version_key(release.version)):
            return installed
        return release.version

    @property
    def release_url(self) -> str | None:
        return self.release.url if self.release else None

    @property
    def release_summary(self) -> str | None:
        summary = self.release.summary if self.release else None
        if summary and len(summary) > SUMMARY_MAX_LENGTH:
            summary = summary[: SUMMARY_MAX_LENGTH - 1] + "…"
        return summary

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # État brut de `update/` (non documenté) : seul `up_to_date` est connu.
        update = self.coordinator.data.firmware_update
        return {"box_update_state": update.get("state")} if update else None

    async def async_release_notes(self) -> str | None:
        return self.release.notes if self.release else None
