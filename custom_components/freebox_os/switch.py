"""Interrupteurs Freebox OS : Wi-Fi global de la box, accès Internet des profils."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import FreeboxConfigEntry
from .api import FreeboxApiError, FreeboxPermissionError
from .coordinator import FreeboxDataUpdateCoordinator
from .const import ACCESS_DENIED
from .entity import FreeboxEntity
from .parental import FreeboxProfileEntity, async_track_profiles


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if coordinator.data.wifi is not None:
        async_add_entities([FreeboxWifiSwitch(coordinator)])
    async_track_profiles(
        entry,
        coordinator,
        async_add_entities,
        lambda device_id, profile: [FreeboxProfileAccessSwitch(coordinator, device_id, profile)],
    )


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


class FreeboxProfileAccessSwitch(FreeboxProfileEntity, SwitchEntity):
    """Accès Internet d'un profil : couper = pause sans limite, rétablir = comme
    le bouton lecture de Freebox OS. Pour une durée, utiliser les actions
    `freebox_os.block_internet` / `freebox_os.allow_internet`.
    """

    _attr_translation_key = "internet_access"

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, router_device_id: str, profile: dict[str, Any]) -> None:
        super().__init__(coordinator, router_device_id, profile, "internet_access")

    @property
    def is_on(self) -> bool | None:
        profile = self.profile
        return profile.get("current_mode") != ACCESS_DENIED if profile else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self.profile or {}
        until = profile.get("override_until") or 0
        return {
            "manual": bool(profile.get("override")),
            "manual_until": dt_util.utc_from_timestamp(until).isoformat()
            if profile.get("override") and until
            else None,
            "schedule_mode": profile.get("rule_mode"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_allow()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_block()
