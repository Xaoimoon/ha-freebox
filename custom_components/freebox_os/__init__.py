"""Intégration Freebox OS pour Home Assistant (en développement).

Squelette : aucune plateforme n'est encore déclarée et `config_flow` est
désactivé dans le manifeste tant que l'appairage par jeton d'application
n'est pas écrit.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN  # noqa: F401

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure une Freebox à partir d'une entrée de configuration."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée de configuration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
