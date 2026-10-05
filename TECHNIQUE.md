# Notes techniques : API Freebox OS

Notes de travail pour la cartographie de l'API. Tout ce qui n'est pas marqué
**vérifié** est à confirmer sur la Freebox de la maison (Ultra, v9), avec la version de
Freebox OS du moment, avant d'être utilisé dans le code.

## Découverte

- `GET http://mafreebox.freebox.fr/api_version` : version de l'API, préfixe des URL
  (`api_base_url`), domaine et port HTTPS, modèle de la box. Point de départ de tout le reste :
  le préfixe versionné ne doit pas être écrit en dur. **Vérifié le 2026-10-05** sur la box
  de la maison : `fbxgw9-r1` (Freebox v9 r1), API `16.0`, préfixe `/api/v16/`, firmware 4.12.3.

## Authentification (jeton d'application)

1. `POST login/authorize/` avec l'identité de l'application (`app_id`, `app_name`,
   `app_version`, `device_name`) → `app_token` et `track_id`.
2. L'utilisateur valide la demande **sur l'écran de la Freebox**.
3. `GET login/authorize/{track_id}` jusqu'à ce que le statut passe de `pending` à `granted`.
4. Pour chaque session : `GET login/` (défi `challenge`), puis `POST login/session/` avec
   `password = HMAC-SHA1(app_token, challenge)` → jeton de session, envoyé ensuite dans
   l'en-tête `X-Fbx-App-Auth`.

**Vérifié le 2026-10-05** (`api.py`, avec le jeton de l'application Orbital). Erreurs
observées ou documentées : session expirée → HTTP 403 `auth_required` (le client rouvre la
session une fois) ; jeton révoqué à l'ouverture → `invalid_token` (réappairage) ; droit
manquant → `insufficient_rights` ; endpoint absent → HTTP 404 `invalid_request`. Les
endpoints de liste omettent `result` quand la liste est vide.

Les droits de l'application (paramètres, appels, contrôle parental, domotique…) se règlent
ensuite dans l'interface de Freebox OS. Le jeton d'application est un secret : il vit dans
l'entrée de configuration de Home Assistant (`.storage`), jamais dans Git ni dans les logs.

En HTTPS, la Freebox présente un certificat signé par l'autorité de Free : la chaîne doit
être fournie au client HTTP, ne pas désactiver la vérification.

## Domaines de l'API à cartographier

| Domaine | Intérêt | Sur la v9 |
|---|---|---|
| `connection/` | État, débits, **compteurs cumulés** `bytes_down`/`bytes_up` (octets), IPv4/IPv6 | **vérifié** (media `ftth`, type `ethernet`) |
| `connection/ftth/` | SFP fibre : signal, `sfp_pwr_rx`/`sfp_pwr_tx` en centièmes de dBm | **vérifié** (lien `pon`) |
| `system/` | Firmware, `uptime_val` (s), `sensors` (°C : `temp_cpu0..3`, `temp_hdd`, `temp_t1`), `fans` (tr/min) | **vérifié** |
| `lan/browser/pub/` | Appareils connectés (présence) : ~125 hôtes, `active`, `l2ident`, `l3connectivities` | **vérifié** |
| `switch/status/` | Ports Ethernet : lien, vitesse, MAC vues | **vérifié** (5 ports, dont 9999 = SFP LAN) |
| `storage/disk/` | Disques et partitions (NVMe 2 To « Nas »), température | **vérifié** |
| `wifi/state/`, `wifi/ap/` | Wi-Fi de la box | **vérifié** : désactivé (le Wi-Fi passe par les eero) |
| `call/` | Journal d'appels | à vérifier |
| `home/` | Domotique (alarme, capteurs) | **absent : 404 (vérifié le 2026-10-05)**, propre à la Delta |

Inventaire plus large : le dépôt `orbital` (`src/debug/`) contient le bundle ExtJS de
l'interface Freebox OS (`freebox.js`) et la liste des 167 endpoints qui en sont extraits
(`freebox-api-endpoints.txt`, avec numéros de ligne dans `freebox-api-endpoints-with-lines.csv`) :
c'est la référence pour les paramètres et formats non documentés.

## Correspondance avec la configuration actuelle

La configuration Home Assistant de la maison (dépôt `Homeassistant`) contourne aujourd'hui
les limites de l'intégration officielle dans `custom_packages/freebox.yaml` :

- volumes de trafic calculés en intégrant les débits (`platform: integration`) ;
- compteurs hebdomadaires (`utility_meter`) et statistiques sur 24 h ;
- templates `*_speed_mb` pour l'historique (les vitesses brutes sont exclues du recorder).

Objectif : exposer directement les compteurs cumulés de la box (capteurs
`total_increasing`) pour supprimer ces calculs, puis reporter les `entity_id` dans les
tableaux de bord, les automations et les filtres du recorder.
