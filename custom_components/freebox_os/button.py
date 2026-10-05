"""Boutons Freebox OS : redémarrage, journal d'appels lu, retour au planning d'un profil."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeboxConfigEntry
from .api import FreeboxApiClient, FreeboxApiError
from .coordinator import FreeboxDataUpdateCoordinator
from .entity import FreeboxEntity
from .parental import FreeboxProfileEntity, async_track_profiles


@dataclass(frozen=True, kw_only=True)
class FreeboxButtonEntityDescription(ButtonEntityDescription):
    press_fn: Callable[[FreeboxApiClient], Awaitable[None]]
    needs_calls: bool = False


BUTTONS: tuple[FreeboxButtonEntityDescription, ...] = (
    FreeboxButtonEntityDescription(
        key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda api: api.reboot(),
    ),
    FreeboxButtonEntityDescription(
        key="mark_calls_as_read",
        translation_key="mark_calls_as_read",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda api: api.mark_calls_as_read(),
        needs_calls=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreeboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        FreeboxButton(coordinator, description)
        for description in BUTTONS
        if not description.needs_calls or coordinator.data.calls is not None
    )
    async_track_profiles(
        entry,
        coordinator,
        async_add_entities,
        lambda device_id, profile: [FreeboxProfileResumeButton(coordinator, device_id, profile)],
    )


class FreeboxButton(FreeboxEntity, ButtonEntity):
    entity_description: FreeboxButtonEntityDescription

    def __init__(
        self, coordinator: FreeboxDataUpdateCoordinator, description: FreeboxButtonEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self.coordinator.api)
        except FreeboxApiError as err:
            raise HomeAssistantError(f"Freebox : {err}") from err
        if self.entity_description.needs_calls:
            await self.coordinator.async_request_refresh()


class FreeboxProfileResumeButton(FreeboxProfileEntity, ButtonEntity):
    """Termine une pause ou un accès manuel : le planning du profil reprend la main.
    Indisponible quand aucun mode manuel n'est en cours."""

    _attr_translation_key = "resume_schedule"

    def __init__(self, coordinator: FreeboxDataUpdateCoordinator, router_device_id: str, profile) -> None:
        super().__init__(coordinator, router_device_id, profile, "resume_schedule")

    @property
    def available(self) -> bool:
        return super().available and bool((self.profile or {}).get("override"))

    async def async_press(self) -> None:
        await self.async_resume_schedule()
