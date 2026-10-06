# Documentation technique

Fonctionnement de l'intégration, notes sur l'API Freebox OS, développement et releases.
Côté API, tout ce qui n'est pas marqué **vérifié** est à confirmer sur une vraie Freebox
(référence : Freebox Ultra v9), avec la version de Freebox OS du moment, avant d'être utilisé
dans le code.

## Fonctionnement de l'intégration

- `api.py` : client HTTP de l'API locale (session aiohttp partagée de Home Assistant). Il lit
  `/api_version` à chaque démarrage pour construire le préfixe versionné, ouvre la session à
  la première requête et la rouvre une fois si la box répond `auth_required`.
- `config_flow.py` : appairage par jeton d'application (saisie de l'hôte ou découverte
  zeroconf `_fbx-api._tcp`, attente de la validation sur l'écran de la box dans une étape de
  progression, réappairage si le jeton est révoqué). La box est identifiée par son `uid`.
- `coordinator.py` : un relevé complet toutes les 30 s (système, connexion et journal, fibre
  en FTTH, ports du switch et leurs compteurs, disques, appareils du LAN, appels, Wi-Fi,
  profils de contrôle parental). Une lecture refusée faute de droit (`insufficient_rights`)
  désactive la partie concernée jusqu'au prochain chargement, sans faire échouer le relevé.
- Plateformes `sensor`, `binary_sensor`, `switch`, `button`, `device_tracker` ; `parental.py`
  regroupe les appareils et entités des profils de contrôle parental (ajoutés à la volée),
  `services.py` les actions `block_internet` / `allow_internet` / `resume_schedule`.

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

## Endpoints de l'API

| Domaine | Intérêt | Sur la v9 |
|---|---|---|
| `connection/` | État, débits, **compteurs cumulés** `bytes_down`/`bytes_up` (octets), IPv4/IPv6 | **vérifié** (media `ftth`, type `ethernet`) |
| `connection/ftth/` | SFP fibre : signal, `sfp_pwr_rx`/`sfp_pwr_tx` en centièmes de dBm | **vérifié** (lien `pon`) |
| `connection/logs/` | Changements d'état du lien (`link`) et de la connexion IP (`conn`) : `up`/`down`, horodatés | **vérifié** ; remis à zéro au démarrage de la box (un redémarrage n'y figure pas comme une coupure) |
| `system/` | Firmware, `uptime_val` (s), `sensors` (°C : `temp_cpu0..3`, `temp_hdd`, `temp_t1`), `fans` (tr/min) | **vérifié** |
| `lan/browser/pub/` | Appareils connectés (présence) : ~125 hôtes, `active`, `l2ident`, `l3connectivities` | **vérifié** |
| `switch/status/` | Ports Ethernet : lien, vitesse (texte, « 10 » half sur un port libre), mode, MAC vues | **vérifié** (5 ports, dont 9999 = SFP LAN) |
| `switch/port/{id}/stats/` | Compteurs du port, vus de la box : `rx_good_bytes` / `tx_bytes`, débits, erreurs | **vérifié** ; `switch/port/` sans id renvoie 404 |
| `storage/disk/` | Disques et partitions (NVMe 2 To « Nas »), température | **vérifié** |
| `wifi/state/`, `wifi/ap/` | Wi-Fi de la box | **vérifié** : désactivé (le Wi-Fi passe par les eero) |
| `call/log/` | Journal d'appels (`type` missed/accepted/outgoing, `new`) ; `call/log/mark_all_as_read/` (POST) | **vérifié** |
| `wifi/config/` | Wi-Fi global : `enabled` (PUT pour l'activer ou le couper) | **vérifié** |
| `network_control/` | Profils de contrôle parental : `current_mode`, `rule_mode`, `override*`, `next_change`, appareils (`hosts`) | **vérifié** ; le PUT exige le profil complet (voir ci-dessous) |
| `ws/event` | WebSocket d'événements (`register` puis notifications `lan_host_l3addr_reachable/unreachable`…) | **vérifié**, non utilisé : un événement par adresse IPv4/IPv6, très bavard |
| `update/` | État de la mise à jour du firmware : `{"state": "up_to_date"}` | **vérifié** le 2026-10-06 ; **non documenté**, absent du bundle Freebox OS : les autres valeurs de `state` sont inconnues, toutes traitées comme « mise à jour en attente » |
| `home/` | Domotique (alarme, capteurs) | **absent : 404 (vérifié le 2026-10-05)**, propre à la Delta |

### Contrôle parental

Les actions reprennent celles de l'interface Freebox OS (`NetworkControlModel.doAction`) :
pause = `override: true`, `override_mode: "denied"`, `override_until` (timestamp, 0 = sans
limite) ; accès manuel = `override_mode: "allowed"`, jusqu'à l'échéance ou au `next_change` du
planning ; retour au planning = `override: false`. La box refuse un PUT partiel (« Liste
d'adresses MAC manquante ») : il faut renvoyer `profile_name`, `profile_icon`,
`override_mode`, `current_mode`, `override_until`, `override`, `macs` et `cdayranges`. À
l'échéance d'une pause, la box repasse d'elle-même `override` à false (**vérifié** sur une
pause d'une minute).

### Inventaire

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

Les compteurs cumulés de la box sont exposés : capteurs « Données reçues » /
« Données envoyées » (`bytes_down` / `bytes_up`, octets depuis le démarrage de la box,
`total_increasing`, affichés en Go). Correspondance pour la migration :

| Aujourd'hui (`freebox.yaml`) | Remplacement |
|---|---|
| `sensor.freebox_*_volume_total` (intégration des débits) | « Données reçues / envoyées » : les vrais compteurs, sans dérive d'intégration |
| `utility_meter` `download_hebdo` / `upload_hebdo` | même `utility_meter`, avec pour source les nouveaux capteurs |
| templates `MB Received/Sent Weekly` | unité d'affichage du `utility_meter` (Mo) dans les réglages de l'entité |
| templates `*_speed_mb` (Mbit/s) | unité d'affichage des capteurs de débit (`data_rate`, convertible en Mbit/s) |

Restent ensuite à reporter les `entity_id` dans les tableaux de bord, les automations et les
filtres du recorder.

## Développement

Les scripts de `scripts/` suivent [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint).
Ils se lancent dans un environnement virtuel Python 3.14 (Linux, macOS ou WSL) :

```bash
scripts/setup     # installe Home Assistant (même version que la production)
scripts/test      # lance les tests
scripts/develop   # démarre un Home Assistant de test avec l'intégration, dans ./config
```

Home Assistant ne démarre pas nativement sous Windows : y lancer plutôt un conteneur, avec
l'intégration montée en direct (redémarrer le conteneur après une modification du code) :

```powershell
docker run -d --name ha-freebox-dev -p 8123:8123 -e TZ=Europe/Paris `
  -v "${PWD}\config:/config" -v "${PWD}\custom_components:/config/custom_components" `
  ghcr.io/home-assistant/home-assistant:2026.9.4
```

Le dossier `config/` (gitignored) contient alors l'entrée de configuration et le jeton
d'application : ne jamais le committer. Pour tester un comportement propre à une version de
Home Assistant (par exemple le renommage des appareils par les `ScannerEntity` depuis la
2026.9), vérifier dans ce conteneur et pas seulement avec la version installée localement.

### Tests

```bash
scripts/test
```

Suite pytest ciblée : `api.py` (HTTP, session, erreurs, mockés avec `aioresponses`, sans
appel réseau), coordinateur, entités, contrôle parental, connexion et ports, testés contre
des réponses réelles de la box anonymisées (`tests/fixtures/` : IP, MAC, numéros de série,
noms d'appareils et de profils remplacés). Pas de tests du config flow, qui demanderaient
`pytest-homeassistant-custom-component`.

## Releases

Les versions sont calculées automatiquement à partir des messages de commit
([Conventional Commits](https://www.conventionalcommits.org/fr/)) par le workflow
`.forgejo/workflows/release.yml`, à chaque push sur `main` :

- `fix: …` ou `perf: …` → version corrective (0.1.**1**) ;
- `feat: …` → nouvelle fonctionnalité (0.**2**.0) ;
- `feat!: …` ou un pied de commit `BREAKING CHANGE:` → version majeure (**1**.0.0) ;
- les autres types (`docs`, `chore`, `refactor`, `test`, `ci`…) ne déclenchent pas de release.

`python scripts/bump_version.py --dry-run` affiche la prochaine version sans rien modifier.
Le workflow met à jour `manifest.json`, crée le tag et la release sur brokk.

### Releases GitHub et HACS

Le dépôt principal est sur [brokk](https://brokk.xaoimoon.fr/xaoimoon/ha-freebox) ; GitHub en
est une copie (miroir push), utilisée par HACS. Le workflow `.github/workflows/release.yml`
transforme chaque tag reçu en release GitHub, que HACS propose comme mise à jour.
