"""Client HTTP bas niveau pour l'API locale de Freebox OS.

Authentification par jeton d'application (voir TECHNIQUE.md) : le jeton est
obtenu une fois par appairage, validé sur l'écran de la box, puis chaque
session s'ouvre par un défi HMAC-SHA1. La session expire d'elle-même : le
client la rouvre de façon transparente quand la box répond `auth_required`.

Le client ne possède pas sa session aiohttp (pas de cookies côté Freebox) :
dans Home Assistant on lui passe la session partagée.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import aiohttp

from .const import (
    CALL_LOG_ENDPOINT,
    CALL_LOG_MARK_READ_ENDPOINT,
    CONNECTION_ENDPOINT,
    CONNECTION_FTTH_ENDPOINT,
    CONNECTION_LOGS_ENDPOINT,
    LAN_HOSTS_ENDPOINT,
    LAN_INTERFACES_ENDPOINT,
    LOGIN_AUTHORIZE_ENDPOINT,
    LOGIN_ENDPOINT,
    LOGIN_LOGOUT_ENDPOINT,
    LOGIN_SESSION_ENDPOINT,
    NETWORK_CONTROL_ENDPOINT,
    STORAGE_DISK_ENDPOINT,
    STORAGE_RAID_ENDPOINT,
    SWITCH_PORT_STATS_ENDPOINT,
    SWITCH_STATUS_ENDPOINT,
    SYSTEM_ENDPOINT,
    SYSTEM_REBOOT_ENDPOINT,
    UPDATE_ENDPOINT,
    WIFI_CONFIG_ENDPOINT,
    WIFI_STATE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Codes d'erreur qui signalent une session expirée ou absente : on rouvre.
_SESSION_ERRORS = {"auth_required", "invalid_session"}
# Codes d'erreur à l'ouverture de session qui exigent un nouvel appairage.
_TOKEN_ERRORS = {"invalid_token", "pending_token"}
# Champs d'un profil de contrôle parental que la box attend à chaque PUT :
# elle refuse une mise à jour partielle (« Liste d'adresses MAC manquante »).
_PROFILE_FIELDS = (
    "profile_name",
    "profile_icon",
    "override_mode",
    "current_mode",
    "override_until",
    "override",
    "macs",
    "cdayranges",
)


class FreeboxApiError(Exception):
    """Erreur générique de l'API Freebox."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class FreeboxConnectionError(FreeboxApiError):
    """La Freebox est injoignable."""


class FreeboxAuthError(FreeboxApiError):
    """Jeton d'application refusé (révoqué, jamais validé) : réappairer."""


class FreeboxPermissionError(FreeboxApiError):
    """L'application n'a pas le droit requis (à accorder dans Freebox OS)."""


def build_api_url(host: str, port: int, api_info: dict[str, Any], use_https: bool = False) -> str:
    """Construit le préfixe versionné (`http://host:port/api/v16/`) à partir
    de la réponse de `/api_version`.
    """
    scheme = "https" if use_https else "http"
    base = api_info.get("api_base_url", "/api/")
    major = str(api_info["api_version"]).split(".", 1)[0]
    return f"{scheme}://{host}:{port}{base}v{major}/"


async def async_get_api_version(
    session: aiohttp.ClientSession, host: str, port: int, use_https: bool = False
) -> dict[str, Any]:
    """Lit `/api_version` (sans authentification) : modèle, version d'API, uid."""
    scheme = "https" if use_https else "http"
    try:
        async with session.get(f"{scheme}://{host}:{port}/api_version", timeout=REQUEST_TIMEOUT) as resp:
            if not resp.ok:
                raise FreeboxApiError(f"Unexpected status {resp.status} for /api_version")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise FreeboxConnectionError(str(err)) from err
    if not isinstance(data, dict) or "api_version" not in data:
        raise FreeboxApiError("Réponse /api_version inattendue : ce n'est pas une Freebox ?")
    return data


class FreeboxApiClient:
    """Enveloppe asynchrone fine autour de l'API locale de Freebox OS."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        app_id: str,
        app_token: str | None = None,
    ) -> None:
        self._session = session
        self._api_url = api_url
        self._app_id = app_id
        self._app_token = app_token
        self._session_token: str | None = None
        self.permissions: dict[str, bool] = {}
        self._login_lock = asyncio.Lock()

    async def _raw(
        self, method: str, endpoint: str, *, authenticated: bool, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        headers = {}
        if authenticated and self._session_token:
            headers["X-Fbx-App-Auth"] = self._session_token
        try:
            async with self._session.request(
                method,
                f"{self._api_url}{endpoint}",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                **kwargs,
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    raise FreeboxApiError(
                        f"Réponse non JSON ({resp.status}) pour {method} {endpoint}"
                    ) from err
                return resp.status, data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FreeboxConnectionError(str(err)) from err

    @staticmethod
    def _unwrap(method: str, endpoint: str, status: int, data: Any) -> Any:
        """Rend `result` d'une réponse `{success, result}` ou lève l'erreur adaptée."""
        if isinstance(data, dict) and data.get("success"):
            return data.get("result")
        code = data.get("error_code") if isinstance(data, dict) else None
        msg = (data.get("msg") if isinstance(data, dict) else None) or f"HTTP {status}"
        if code == "insufficient_rights":
            raise FreeboxPermissionError(f"{method} {endpoint}: {msg}", code)
        raise FreeboxApiError(f"{method} {endpoint}: {msg}", code)

    # --- Appairage -------------------------------------------------------

    async def authorize(self, app_name: str, app_version: str, device_name: str) -> int:
        """Demande un jeton d'application. L'utilisateur doit valider sur la
        box ; suivre avec `get_authorization_status(track_id)`. Le jeton est
        conservé dans le client (propriété `app_token`).
        """
        status, data = await self._raw(
            "POST",
            LOGIN_AUTHORIZE_ENDPOINT,
            authenticated=False,
            json={
                "app_id": self._app_id,
                "app_name": app_name,
                "app_version": app_version,
                "device_name": device_name,
            },
        )
        result = self._unwrap("POST", LOGIN_AUTHORIZE_ENDPOINT, status, data)
        self._app_token = result["app_token"]
        return int(result["track_id"])

    async def get_authorization_status(self, track_id: int) -> str:
        """Statut de l'appairage : unknown, pending, timeout, granted, denied."""
        endpoint = f"{LOGIN_AUTHORIZE_ENDPOINT}{track_id}"
        status, data = await self._raw("GET", endpoint, authenticated=False)
        return self._unwrap("GET", endpoint, status, data)["status"]

    @property
    def app_token(self) -> str | None:
        return self._app_token

    # --- Session ---------------------------------------------------------

    async def open_session(self) -> None:
        """Ouvre une session : défi `login/`, puis HMAC-SHA1(app_token, défi)."""
        if not self._app_token:
            raise FreeboxAuthError("Aucun jeton d'application : appairage requis")

        status, data = await self._raw("GET", LOGIN_ENDPOINT, authenticated=False)
        challenge = self._unwrap("GET", LOGIN_ENDPOINT, status, data)["challenge"]
        password = hmac.new(
            self._app_token.encode(), challenge.encode(), hashlib.sha1
        ).hexdigest()

        status, data = await self._raw(
            "POST",
            LOGIN_SESSION_ENDPOINT,
            authenticated=False,
            json={"app_id": self._app_id, "password": password},
        )
        try:
            result = self._unwrap("POST", LOGIN_SESSION_ENDPOINT, status, data)
        except FreeboxApiError as err:
            if err.error_code in _TOKEN_ERRORS:
                raise FreeboxAuthError(str(err), err.error_code) from err
            raise
        self._session_token = result["session_token"]
        self.permissions = result.get("permissions") or {}

    async def close_session(self) -> None:
        """Ferme la session (au mieux : rien à rattraper en cas d'échec)."""
        if not self._session_token:
            return
        try:
            await self._raw("POST", LOGIN_LOGOUT_ENDPOINT, authenticated=True)
        except FreeboxApiError:
            _LOGGER.debug("Logout request failed, ignoring", exc_info=True)
        self._session_token = None

    async def _ensure_session(self, stale_token: str | None) -> None:
        """Rouvre la session, sauf si une autre tâche vient de le faire."""
        async with self._login_lock:
            if self._session_token is None or self._session_token == stale_token:
                await self.open_session()

    async def request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Appel authentifié ; rouvre la session une fois si elle a expiré."""
        if self._session_token is None:
            await self._ensure_session(None)
        token = self._session_token
        status, data = await self._raw(method, endpoint, authenticated=True, **kwargs)
        if isinstance(data, dict) and not data.get("success") and data.get("error_code") in _SESSION_ERRORS:
            _LOGGER.debug("Session expired, reopening")
            await self._ensure_session(token)
            status, data = await self._raw(method, endpoint, authenticated=True, **kwargs)
        return self._unwrap(method, endpoint, status, data)

    # --- Lectures --------------------------------------------------------

    async def get_connection(self) -> dict[str, Any]:
        """État du lien WAN, débits instantanés et compteurs cumulés (octets)."""
        return await self.request("GET", CONNECTION_ENDPOINT)

    async def get_connection_ftth(self) -> dict[str, Any]:
        """Module SFP fibre : présence, signal, puissances optiques."""
        return await self.request("GET", CONNECTION_FTTH_ENDPOINT)

    async def get_connection_logs(self) -> list[dict[str, Any]]:
        """Changements d'état du lien et de la connexion depuis le démarrage de la box."""
        return await self.request("GET", CONNECTION_LOGS_ENDPOINT) or []

    async def get_system(self) -> dict[str, Any]:
        """Modèle, firmware, uptime, températures et ventilateurs."""
        return await self.request("GET", SYSTEM_ENDPOINT)

    async def get_firmware_update(self) -> dict[str, Any]:
        """État de la mise à jour du firmware (endpoint non documenté)."""
        return await self.request("GET", UPDATE_ENDPOINT)

    async def get_lan_interfaces(self) -> list[dict[str, Any]]:
        """Interfaces du navigateur LAN (`pub`, `wifiguest`…)."""
        return await self.request("GET", LAN_INTERFACES_ENDPOINT) or []

    async def get_lan_hosts(self, interface: str = "pub") -> list[dict[str, Any]]:
        """Appareils vus sur une interface LAN."""
        return await self.request("GET", LAN_HOSTS_ENDPOINT.format(interface=interface)) or []

    async def get_switch_status(self) -> list[dict[str, Any]]:
        """Ports Ethernet du switch : lien, vitesse, MAC vues."""
        return await self.request("GET", SWITCH_STATUS_ENDPOINT) or []

    async def get_switch_port_stats(self, port_id: int) -> dict[str, Any]:
        """Compteurs d'un port du switch : octets, paquets, erreurs, débits."""
        return await self.request("GET", SWITCH_PORT_STATS_ENDPOINT.format(port_id=port_id)) or {}

    async def get_storage_disks(self) -> list[dict[str, Any]]:
        """Disques internes et externes, avec leurs partitions."""
        return await self.request("GET", STORAGE_DISK_ENDPOINT) or []

    async def get_storage_raids(self) -> list[dict[str, Any]]:
        """Grappes RAID (aucune sur la v9 : `result` absent)."""
        return await self.request("GET", STORAGE_RAID_ENDPOINT) or []

    async def get_wifi_state(self) -> dict[str, Any]:
        """État global du Wi-Fi de la box."""
        return await self.request("GET", WIFI_STATE_ENDPOINT)

    async def get_wifi_config(self) -> dict[str, Any]:
        """Configuration globale du Wi-Fi (`enabled`, `power_saving`…)."""
        return await self.request("GET", WIFI_CONFIG_ENDPOINT)

    async def set_wifi_enabled(self, enabled: bool) -> dict[str, Any]:
        """Active ou coupe tout le Wi-Fi de la box (droit `settings`)."""
        return await self.request("PUT", WIFI_CONFIG_ENDPOINT, json={"enabled": enabled})

    async def get_call_log(self) -> list[dict[str, Any]]:
        """Journal d'appels (droit `calls`)."""
        return await self.request("GET", CALL_LOG_ENDPOINT) or []

    async def mark_calls_as_read(self) -> None:
        """Marque tout le journal d'appels comme lu (droit `calls`)."""
        await self.request("POST", CALL_LOG_MARK_READ_ENDPOINT)

    async def get_network_control(self) -> list[dict[str, Any]]:
        """Profils de contrôle parental, avec leurs appareils (droit `parental`)."""
        return await self.request("GET", NETWORK_CONTROL_ENDPOINT) or []

    async def update_network_control(self, profile: dict[str, Any], **changes: Any) -> dict[str, Any]:
        """Modifie un profil : renvoie le profil complet, avec les changements."""
        body = {key: profile.get(key) for key in _PROFILE_FIELDS}
        body["override_until"] = body["override_until"] or 0
        body.update(changes)
        return await self.request(
            "PUT", f"{NETWORK_CONTROL_ENDPOINT}{profile['profile_id']}", json=body
        )

    async def reboot(self) -> None:
        """Redémarre la Freebox (droit `settings`)."""
        await self.request("POST", SYSTEM_REBOOT_ENDPOINT)
