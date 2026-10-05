"""Contrôle parental : un appareil par profil de Freebox OS.

Rien à configurer : les profils créés dans Freebox OS (Paramètres > Contrôle
parental) apparaissent tels quels, y compris ceux ajoutés après coup, sans
recharger l'intégration. Un profil supprimé de Freebox OS rend ses entités
indisponibles ; son appareil peut alors être supprimé de Home Assistant.

Les actions reprennent celles de l'interface de Freebox OS :
- bloquer : pause manuelle (`override_mode` denied), pour une durée ou sans limite ;
- autoriser : accès manuel (`override_mode` allowed), pour une durée ou
  jusqu'au prochain changement du planning ;
- reprendre le planning : fin du mode manuel (`override` false).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import FreeboxApiError, FreeboxPermissionError
from .const import ACCESS_ALLOWED, ACCESS_DENIED, DOMAIN
from .coordinator import FreeboxDataUpdateCoordinator
from .entity import MANUFACTURER


def profile_identifier(router_mac: str, profile_id: int) -> str:
    return f"{router_mac}_profile_{profile_id}"


def profile_device_info(router_mac: str, router_device_id: str, profile: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, profile_identifier(router_mac, profile["profile_id"]))},
        name=profile.get("profile_name") or f"Profil {profile['profile_id']}",
        manufacturer=MANUFACTURER,
        model="Profil de contrôle parental",
        via_device_id=router_device_id,
    )


def _until(duration: timedelta | None) -> int:
    """Échéance au format de la box : timestamp Unix, 0 pour « sans limite »."""
    return int((dt_util.utcnow() + duration).timestamp()) if duration else 0


class FreeboxProfileEntity(CoordinatorEntity[FreeboxDataUpdateCoordinator]):
    """Entité d'un profil de contrôle parental."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FreeboxDataUpdateCoordinator,
        router_device_id: str,
        profile: dict[str, Any],
        key: str,
    ) -> None:
        super().__init__(coordinator)
        router_mac = coordinator.data.system["mac"]
        self._profile_id: int = profile["profile_id"]
        self._attr_unique_id = f"{profile_identifier(router_mac, self._profile_id)} {key}"
        self._attr_device_info = profile_device_info(router_mac, router_device_id, profile)

    @property
    def profile(self) -> dict[str, Any] | None:
        return (self.coordinator.data.profiles or {}).get(self._profile_id)

    @property
    def available(self) -> bool:
        return super().available and self.profile is not None

    async def _async_update_profile(self, **changes: Any) -> None:
        profile = self.profile
        if profile is None:
            raise HomeAssistantError("Ce profil n'existe plus dans Freebox OS")
        try:
            await self.coordinator.api.update_network_control(profile, **changes)
        except FreeboxPermissionError as err:
            raise HomeAssistantError(
                "L'application n'a pas le droit « Contrôle parental » dans Freebox OS"
            ) from err
        except FreeboxApiError as err:
            raise HomeAssistantError(f"Freebox : {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_block(self, duration: timedelta | None = None) -> None:
        """Coupe l'accès à Internet, pour `duration` ou jusqu'à nouvel ordre."""
        await self._async_update_profile(
            override=True, override_mode=ACCESS_DENIED, override_until=_until(duration)
        )

    async def async_allow(self, duration: timedelta | None = None) -> None:
        """Rétablit l'accès. Sans durée : si le planning autorise déjà l'accès,
        on y revient ; sinon l'accès est ouvert jusqu'au prochain changement
        prévu par le planning (comme dans Freebox OS).
        """
        profile = self.profile or {}
        if duration is None and profile.get("rule_mode") == ACCESS_ALLOWED:
            await self.async_resume_schedule()
            return
        until = _until(duration) if duration else profile.get("next_change") or 0
        await self._async_update_profile(
            override=True, override_mode=ACCESS_ALLOWED, override_until=until
        )

    async def async_resume_schedule(self) -> None:
        """Termine le mode manuel : le planning du profil s'applique de nouveau."""
        await self._async_update_profile(override=False)


def async_track_profiles(
    entry,
    coordinator: FreeboxDataUpdateCoordinator,
    async_add_entities: Callable[[list[Entity]], None],
    build: Callable[[str, dict[str, Any]], list[Entity]],
) -> None:
    """Ajoute les entités de chaque profil, y compris ceux créés après coup."""
    added: set[int] = set()
    router_device_id = entry.runtime_data.router_device_id

    @callback
    def add_new_profiles() -> None:
        new: list[Entity] = []
        for profile_id, profile in (coordinator.data.profiles or {}).items():
            if profile_id not in added:
                added.add(profile_id)
                new.extend(build(router_device_id, profile))
        if new:
            async_add_entities(new)

    add_new_profiles()
    entry.async_on_unload(coordinator.async_add_listener(add_new_profiles))
