# Notes techniques : API Freebox OS

Notes de travail pour la cartographie de l'API. Tout ce qui n'est pas marqué
**vérifié** est à confirmer sur la Freebox de la maison (Ultra, v9), avec la version de
Freebox OS du moment, avant d'être utilisé dans le code.

## Découverte

- `GET http://mafreebox.freebox.fr/api_version` : version de l'API, préfixe des URL
  (`api_base_url`), domaine et port HTTPS, modèle de la box. Point de départ de tout le reste :
  le préfixe versionné ne doit pas être écrit en dur.

## Authentification (jeton d'application)

1. `POST login/authorize/` avec l'identité de l'application (`app_id`, `app_name`,
   `app_version`, `device_name`) → `app_token` et `track_id`.
2. L'utilisateur valide la demande **sur l'écran de la Freebox**.
3. `GET login/authorize/{track_id}` jusqu'à ce que le statut passe de `pending` à `granted`.
4. Pour chaque session : `GET login/` (défi `challenge`), puis `POST login/session/` avec
   `password = HMAC-SHA1(app_token, challenge)` → jeton de session, envoyé ensuite dans
   l'en-tête `X-Fbx-App-Auth`.

Les droits de l'application (paramètres, appels, contrôle parental, domotique…) se règlent
ensuite dans l'interface de Freebox OS. Le jeton d'application est un secret : il vit dans
l'entrée de configuration de Home Assistant (`.storage`), jamais dans Git ni dans les logs.

En HTTPS, la Freebox présente un certificat signé par l'autorité de Free : la chaîne doit
être fournie au client HTTP, ne pas désactiver la vérification.

## Domaines de l'API à cartographier

| Domaine | Intérêt | Sur la v9 |
|---|---|---|
| `connection/` | État, débits, **compteurs cumulés** de trafic, IPv4/IPv6 | à vérifier |
| `wifi/` | Points d'accès, bandes, invités | à vérifier |
| `lan/browser/` | Appareils connectés (présence) | à vérifier |
| `storage/` | Disques et partitions | à vérifier |
| `system/` | Modèle, firmware, températures, ventilateurs, uptime | à vérifier |
| `call/` | Journal d'appels | à vérifier |
| `home/` | Domotique (alarme, capteurs) | **absent : 404 (vérifié le 2026-10-05)**, propre à la Delta |

## Correspondance avec la configuration actuelle

La configuration Home Assistant de la maison (dépôt `Homeassistant`) contourne aujourd'hui
les limites de l'intégration officielle dans `custom_packages/freebox.yaml` :

- volumes de trafic calculés en intégrant les débits (`platform: integration`) ;
- compteurs hebdomadaires (`utility_meter`) et statistiques sur 24 h ;
- templates `*_speed_mb` pour l'historique (les vitesses brutes sont exclues du recorder).

Objectif : exposer directement les compteurs cumulés de la box (capteurs
`total_increasing`) pour supprimer ces calculs, puis reporter les `entity_id` dans les
tableaux de bord, les automations et les filtres du recorder.
