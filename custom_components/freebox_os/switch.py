"""Interrupteur Freebox OS : Wi-Fi global de la box."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeboxConfigEntry
from .api import FreeboxApiError, FreeboxPermissionError
from .coordinator import FreeboxDataUpdateCoordinator
from .entity import FreeboxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if coordinator.data.wifi is not None:
        async_add_entities([FreeboxWifiSwitch(coordinator)])


class FreeboxWifiSwitch(FreeboxEntity, SwitchEntity):
    _attr_translation_key = "wifi"

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "wifi")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.wifi is not None

    @property
    def is_on(self) -> bool | None:
        wifi = self.coordinator.data.wifi
        return bool(wifi["enabled"]) if wifi else None

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self.coordinator.api.set_wifi_enabled(enabled)
        except FreeboxPermissionError as err:
            raise HomeAssistantError(
                "L'application n'a pas le droit « Modification des réglages de la Freebox »"
            ) from err
        except FreeboxApiError as err:
            raise HomeAssistantError(f"Freebox : {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
