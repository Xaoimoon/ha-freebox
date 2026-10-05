"""Actions du contrôle parental, ciblant l'interrupteur « Accès Internet » d'un profil."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.service import async_register_platform_entity_service

from .const import DOMAIN
from .parental import FreeboxProfileEntity

ATTR_DURATION = "duration"

SERVICE_BLOCK_INTERNET = "block_internet"
SERVICE_ALLOW_INTERNET = "allow_internet"
SERVICE_RESUME_SCHEDULE = "resume_schedule"

DURATION_SCHEMA = {vol.Optional(ATTR_DURATION): cv.positive_time_period}


def _profile(entity: Entity) -> FreeboxProfileEntity:
    if not isinstance(entity, FreeboxProfileEntity):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_profile",
            translation_placeholders={"entity_id": entity.entity_id},
        )
    return entity


async def _block(entity: Entity, call: ServiceCall) -> None:
    await _profile(entity).async_block(call.data.get(ATTR_DURATION))


async def _allow(entity: Entity, call: ServiceCall) -> None:
    await _profile(entity).async_allow(call.data.get(ATTR_DURATION))


async def _resume(entity: Entity, call: ServiceCall) -> None:
    await _profile(entity).async_resume_schedule()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for name, func, schema in (
        (SERVICE_BLOCK_INTERNET, _block, DURATION_SCHEMA),
        (SERVICE_ALLOW_INTERNET, _allow, DURATION_SCHEMA),
        (SERVICE_RESUME_SCHEDULE, _resume, {}),
    ):
        async_register_platform_entity_service(
            hass, DOMAIN, name, entity_domain=SWITCH_DOMAIN, schema=schema, func=func
        )
