"""Config flow : appairage avec la Freebox par jeton d'application.

1. `user` (ou découverte zeroconf) : adresse de la box, vérifiée par `/api_version`.
2. `link` : à la validation du formulaire, demande d'un jeton à la box.
3. `wait` : attente que l'utilisateur valide sur l'écran de la Freebox.
4. `finish` : ouverture d'une session de contrôle, puis création de l'entrée.

La réauthentification (jeton révoqué dans Freebox OS) reprend à l'étape 2.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.loader import async_get_integration

from .api import (
    FreeboxApiClient,
    FreeboxApiError,
    FreeboxConnectionError,
    async_get_api_version,
    build_api_url,
)
from .const import (
    APP_ID,
    APP_NAME,
    AUTH_STATUS_GRANTED,
    AUTH_STATUS_PENDING,
    CONF_APP_TOKEN,
    DEFAULT_HOST,
    DEFAULT_HTTP_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# La box abandonne la demande d'elle-même au bout d'environ une minute
# (statut `timeout`) ; on arrête d'attendre un peu après.
AUTH_POLL_INTERVAL = 2
AUTH_WAIT_TIMEOUT = 120


class FreeboxOsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère l'appairage d'une Freebox."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = DEFAULT_HOST
        self._port: int = DEFAULT_HTTP_PORT
        self._api: FreeboxApiClient | None = None
        self._track_id: int | None = None
        self._wait_task: asyncio.Task[str] | None = None
        self._error: str | None = None
        self._box_name: str = "Freebox"

    async def _async_probe(self, host: str, port: int) -> dict[str, Any]:
        """Lit `/api_version` et prépare le client d'appairage."""
        session = async_get_clientsession(self.hass)
        info = await async_get_api_version(session, host, port)
        self._host, self._port = host, port
        self._box_name = info.get("box_model_name") or "Freebox"
        self._api = FreeboxApiClient(session, build_api_url(host, port, info), APP_ID)
        return info

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self._async_probe(user_input[CONF_HOST], user_input[CONF_PORT])
            except FreeboxConnectionError:
                errors["base"] = "cannot_connect"
            except FreeboxApiError:
                errors["base"] = "not_a_freebox"
            else:
                await self.async_set_unique_id(info["uid"])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: self._host, CONF_PORT: self._port}
                )
                return await self.async_step_link()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._host): str,
                    vol.Required(CONF_PORT, default=self._port): int,
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        uid = discovery_info.properties.get("uid")
        if not uid:
            return self.async_abort(reason="not_a_freebox")
        await self.async_set_unique_id(uid)
        self._abort_if_unique_id_configured()
        try:
            await self._async_probe(discovery_info.host, discovery_info.port or DEFAULT_HTTP_PORT)
        except FreeboxApiError:
            return self.async_abort(reason="cannot_connect")
        self.context["title_placeholders"] = {"name": self._box_name}
        return await self.async_step_link()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        try:
            await self._async_probe(entry_data[CONF_HOST], entry_data[CONF_PORT])
        except FreeboxApiError:
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_link()

    async def async_step_link(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Explique la validation sur la box ; la demande part à l'envoi du formulaire."""
        errors: dict[str, str] = {}
        if self._error:
            errors["base"], self._error = self._error, None
        elif user_input is not None:
            assert self._api is not None
            integration = await async_get_integration(self.hass, DOMAIN)
            try:
                self._track_id = await self._api.authorize(
                    APP_NAME,
                    str(integration.version),
                    f"Home Assistant ({self.hass.config.location_name})",
                )
            except FreeboxConnectionError:
                errors["base"] = "cannot_connect"
            except FreeboxApiError as err:
                _LOGGER.warning("Demande de jeton refusée par la Freebox : %s", err)
                errors["base"] = "register_failed"
            else:
                return await self.async_step_wait()

        return self.async_show_form(
            step_id="link",
            description_placeholders={"name": self._box_name},
            errors=errors,
        )

    async def _async_wait_for_grant(self) -> str:
        assert self._api is not None and self._track_id is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + AUTH_WAIT_TIMEOUT
        status = AUTH_STATUS_PENDING
        while status == AUTH_STATUS_PENDING and loop.time() < deadline:
            await asyncio.sleep(AUTH_POLL_INTERVAL)
            status = await self._api.get_authorization_status(self._track_id)
        return status

    async def async_step_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._wait_task is None:
            self._wait_task = self.hass.async_create_task(self._async_wait_for_grant())
        if not self._wait_task.done():
            return self.async_show_progress(
                step_id="wait",
                progress_action="wait_for_validation",
                description_placeholders={"name": self._box_name},
                progress_task=self._wait_task,
            )

        task, self._wait_task = self._wait_task, None
        try:
            status = task.result()
        except FreeboxApiError:
            _LOGGER.exception("Suivi de l'appairage interrompu")
            status = "error"
        if status != AUTH_STATUS_GRANTED:
            self._error = {"denied": "auth_denied", "timeout": "auth_timeout"}.get(status, "register_failed")
            return self.async_show_progress_done(next_step_id="link")
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._api is not None
        try:
            # Contrôle : le jeton tout juste accordé ouvre bien une session.
            await self._api.open_session()
            await self._api.close_session()
        except FreeboxApiError:
            _LOGGER.exception("Le jeton accordé n'ouvre pas de session")
            self._error = "register_failed"
            return await self.async_step_link()

        data = {CONF_HOST: self._host, CONF_PORT: self._port, CONF_APP_TOKEN: self._api.app_token}
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_create_entry(title=self._box_name, data=data)
