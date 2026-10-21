"""Dernière version du firmware publiée par Free, lue sur le blog dev.freebox.fr.

La box ne cherche pas de mise à jour tant qu'elle tourne : elle télécharge et
installe la dernière version au redémarrage du Freebox Server. Son API locale
ignore donc qu'une version plus récente existe ; seul le blog l'annonce.
"""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, RELEASES_FEED_URL

_LOGGER = logging.getLogger(__name__)

RELEASES_INTERVAL = timedelta(hours=6)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# « Mise à jour du Freebox Server 4.13.1 » ou, réservée à certains modèles,
# « Mise à jour du Freebox Server (Revolution/Pop/Delta/Ultra) 4.12.4 ».
_TITLE_RE = re.compile(r"^Mise à jour du Freebox Server (?:\((?P<models>[^)]*)\) )?(?P<version>\d+(?:\.\d+)+)$")
# Nom commercial, tel qu'écrit dans les titres du blog, d'après `model_info.name`
# (`fbxgw9-r1`). Seule la v9 (Ultra) est vérifiée.
_MODEL_NAMES = {"6": "Revolution", "7": "Delta", "8": "Pop", "9": "Ultra"}
_MODEL_RE = re.compile(r"^fbxgw(\d+)")
_CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"


@dataclass(frozen=True)
class FreeboxRelease:
    """Une mise à jour du Freebox Server annoncée sur le blog."""

    version: str
    # Modèles concernés ; None quand le titre n'en cite aucun (tous les modèles).
    models: tuple[str, ...] | None
    url: str | None
    summary: str | None
    notes: str | None

    def applies_to(self, model: str | None) -> bool:
        return self.models is None or model in self.models


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def model_name(model_id: str | None) -> str | None:
    """`fbxgw9-r1` → `Ultra` ; None pour un modèle inconnu."""
    match = _MODEL_RE.match(model_id or "")
    return _MODEL_NAMES.get(match.group(1)) if match else None


def latest_release(releases: list[FreeboxRelease], model: str | None) -> FreeboxRelease | None:
    """Dernière version publiée pour ce modèle (nom commercial, voir `model_name`).

    Un modèle inconnu ne retient que les annonces sans liste de modèles.
    """
    candidates = [release for release in releases if release.applies_to(model)]
    return max(candidates, key=lambda release: version_key(release.version), default=None)


def html_to_markdown(text: str) -> str:
    """Notes de version (HTML WordPress simple) en Markdown pour Home Assistant."""
    text = re.sub(r"<h\d[^>]*>(.*?)</h\d>", r"\n### \1\n", text, flags=re.S)
    text = re.sub(r"\s*<li[^>]*>", "\n- ", text)
    text = re.sub(r"</p>|<br\s*/?>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_feed(content: str) -> list[FreeboxRelease]:
    """Mises à jour du Freebox Server présentes dans le flux RSS du blog."""
    releases = []
    for item in ET.fromstring(content).iter("item"):
        match = _TITLE_RE.match(html.unescape((item.findtext("title") or "").strip()))
        if match is None:
            continue
        models = match.group("models")
        notes = item.findtext(_CONTENT_TAG)
        releases.append(
            FreeboxRelease(
                version=match.group("version"),
                models=tuple(name.strip() for name in models.split("/")) if models else None,
                url=item.findtext("link"),
                summary=html.unescape(item.findtext("description") or "").strip() or None,
                notes=html_to_markdown(notes) if notes else None,
            )
        )
    return releases


class FreeboxReleasesCoordinator(DataUpdateCoordinator[list[FreeboxRelease]]):
    """Relit le flux du blog toutes les 6 h, indépendamment de la box."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_releases",
            update_interval=RELEASES_INTERVAL,
        )

    async def _async_update_data(self) -> list[FreeboxRelease]:
        try:
            async with async_get_clientsession(self.hass).get(RELEASES_FEED_URL, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                content = await resp.text()
            return parse_feed(content)
        except (aiohttp.ClientError, TimeoutError, ET.ParseError) as err:
            # Blog injoignable : la dernière version connue reste valable.
            if self.data is not None:
                _LOGGER.debug("Flux des mises à jour Freebox indisponible : %s", err)
                return self.data
            raise UpdateFailed(f"Flux des mises à jour Freebox indisponible : {err}") from err
