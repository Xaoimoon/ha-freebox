"""Tests de la mise à jour du firmware : flux du blog Free et entité `update`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.freebox_os import update
from custom_components.freebox_os.coordinator import FreeboxData
from custom_components.freebox_os.releases import (
    FreeboxRelease,
    FreeboxReleasesCoordinator,
    latest_release,
    model_name,
    parse_feed,
)

FIXTURES = Path(__file__).parent / "fixtures"
MAC = "00:00:5E:00:53:00"


def result(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")).get("result")


def feed() -> list[FreeboxRelease]:
    # Flux réel du 2026-10-21 : 4.13.1 en tête, annonces du répéteur Wifi et
    # article sans version mêlés aux mises à jour du Server.
    return parse_feed((FIXTURES / "blog_feed.xml").read_text(encoding="utf-8"))


def release(version: str, models: tuple[str, ...] | None = None) -> FreeboxRelease:
    return FreeboxRelease(version=version, models=models, url=None, summary=None, notes=None)


def test_parse_real_feed():
    releases = {r.version: r for r in feed()}
    # Seules les mises à jour du Freebox Server : ni répéteur, ni « Support des canaux DFS ».
    assert "2.9.3" not in releases
    assert len(releases) == 15

    latest = releases["4.13.1"]
    assert latest.models is None
    assert latest.url == "https://dev.freebox.fr/blog/?p=22548"
    assert latest.summary.startswith("La mise à jour est disponible depuis le 21 septembre")
    assert latest.notes.splitlines()[0].startswith("La mise à jour est disponible")
    assert "### Corrections:" in latest.notes
    assert "- Correctifs de sécurité" in latest.notes

    assert releases["4.12.4.1"].models == ("Pop",)
    assert releases["4.12.4"].models == ("Revolution", "Pop", "Delta", "Ultra")


def test_model_name():
    assert model_name("fbxgw9-r1") == "Ultra"
    assert model_name("fbxgw8-r2") == "Pop"
    assert model_name("something-else") is None
    assert model_name(None) is None


def test_latest_release_follows_model():
    assert latest_release(feed(), "Ultra").version == "4.13.1"

    # Une version réservée à la Pop ne concerne pas l'Ultra.
    releases = [release("4.12.4", ("Pop", "Ultra")), release("4.12.4.1", ("Pop",)), release("4.12.10", ("Ultra",))]
    assert latest_release(releases, "Ultra").version == "4.12.10"  # comparaison numérique, pas textuelle
    assert latest_release(releases, "Pop").version == "4.12.4.1"
    # Modèle inconnu : seulement les annonces destinées à tous les modèles.
    assert latest_release(releases, None) is None
    assert latest_release(releases + [release("4.13.0")], None).version == "4.13.0"


async def setup_entity(releases: list[FreeboxRelease] | None, **overrides) -> update.FreeboxFirmwareUpdate:
    data = FreeboxData(system=result("system"), connection=result("connection"), **overrides)
    entry = MagicMock()
    entry.runtime_data.coordinator.data = data
    entry.runtime_data.releases.data = releases
    added: list = []
    await update.async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    (entity,) = added
    assert entity.unique_id == f"{MAC} firmware"
    return entity


@pytest.mark.asyncio
async def test_update_entity_announces_newer_release():
    entity = await setup_entity(feed(), firmware_update={"state": "up_to_date"})
    assert entity.installed_version == "4.12.3"
    assert entity.latest_version == "4.13.1"
    assert entity.release_url == "https://dev.freebox.fr/blog/?p=22548"
    assert len(entity.release_summary) <= update.SUMMARY_MAX_LENGTH
    assert "### Corrections:" in await entity.async_release_notes()
    assert entity.extra_state_attributes == {"box_update_state": "up_to_date"}


@pytest.mark.asyncio
async def test_update_entity_without_newer_release():
    # Flux pas encore lu : rien à proposer.
    entity = await setup_entity(None)
    assert entity.latest_version == "4.12.3"
    assert entity.release_url is None
    assert await entity.async_release_notes() is None
    assert entity.extra_state_attributes is None

    # Box en avance sur le blog (bêta) : pas de « mise à jour » vers une version plus ancienne.
    entity = await setup_entity([release("4.12.2")])
    assert entity.latest_version == "4.12.3"


class FakeResponse:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self._text, self._error = text, error

    async def __aenter__(self):
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        pass

    async def text(self) -> str:
        return self._text


@pytest.mark.asyncio
async def test_releases_coordinator_keeps_last_known_releases(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr("custom_components.freebox_os.releases.async_get_clientsession", lambda hass: session)
    coordinator = FreeboxReleasesCoordinator(MagicMock(), MagicMock())

    session.get.return_value = FakeResponse(error=aiohttp.ClientConnectionError("down"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    session.get.return_value = FakeResponse((FIXTURES / "blog_feed.xml").read_text(encoding="utf-8"))
    coordinator.data = await coordinator._async_update_data()
    assert latest_release(coordinator.data, "Ultra").version == "4.13.1"

    # Blog injoignable ensuite : la dernière version connue est conservée.
    session.get.return_value = FakeResponse(error=aiohttp.ClientConnectionError("down"))
    assert await coordinator._async_update_data() is coordinator.data
