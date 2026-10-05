"""Constantes de l'intégration Freebox OS."""

# Domaine distinct de l'intégration officielle `freebox` : les deux peuvent
# tourner en parallèle pendant la migration.
DOMAIN = "freebox_os"

DEFAULT_HOST = "mafreebox.freebox.fr"
DEFAULT_HTTP_PORT = 80

# Identité présentée à la Freebox lors de l'appairage. `APP_ID` lie le jeton
# d'application : le changer impose un nouvel appairage.
APP_ID = "fr.xaoimoon.ha_freebox_os"
APP_NAME = "Home Assistant (Freebox OS)"

CONF_APP_TOKEN = "app_token"

# Statuts de `login/authorize/{track_id}`.
AUTH_STATUS_UNKNOWN = "unknown"  # jeton révoqué ou track_id inconnu
AUTH_STATUS_PENDING = "pending"  # en attente de validation sur la box
AUTH_STATUS_TIMEOUT = "timeout"  # pas de validation dans le délai imparti
AUTH_STATUS_GRANTED = "granted"
AUTH_STATUS_DENIED = "denied"

# Endpoints, relatifs au préfixe versionné (`/api/v16/` sur la v9).
LOGIN_ENDPOINT = "login/"
LOGIN_SESSION_ENDPOINT = "login/session/"
LOGIN_LOGOUT_ENDPOINT = "login/logout/"
LOGIN_AUTHORIZE_ENDPOINT = "login/authorize/"
CONNECTION_ENDPOINT = "connection/"
CONNECTION_FTTH_ENDPOINT = "connection/ftth/"
CONNECTION_LOGS_ENDPOINT = "connection/logs/"
SYSTEM_ENDPOINT = "system/"
LAN_INTERFACES_ENDPOINT = "lan/browser/interfaces/"
LAN_HOSTS_ENDPOINT = "lan/browser/{interface}/"
SWITCH_STATUS_ENDPOINT = "switch/status/"
STORAGE_DISK_ENDPOINT = "storage/disk/"
STORAGE_RAID_ENDPOINT = "storage/raid/"
WIFI_STATE_ENDPOINT = "wifi/state/"
WIFI_CONFIG_ENDPOINT = "wifi/config/"
CALL_LOG_ENDPOINT = "call/log/"
CALL_LOG_MARK_READ_ENDPOINT = "call/log/mark_all_as_read/"
SYSTEM_REBOOT_ENDPOINT = "system/reboot/"
NETWORK_CONTROL_ENDPOINT = "network_control/"

# Modes d'accès d'un profil de contrôle parental (`webonly` : ancien mode,
# que Freebox OS n'accepte plus en écriture).
ACCESS_ALLOWED = "allowed"
ACCESS_DENIED = "denied"
ACCESS_WEBONLY = "webonly"
