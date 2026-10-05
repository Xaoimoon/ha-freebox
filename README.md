# Freebox OS pour Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/docs/faq/custom_repositories)
[![Installations actives](https://img.shields.io/badge/dynamic/json?style=for-the-badge&color=41BDF5&label=Active%20installations&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.freebox_os.total)](https://analytics.home-assistant.io/)
[![Release](https://img.shields.io/github/v/release/Xaoimoon/ha-freebox?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/releases)
[![Licence](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/blob/main/LICENSE)

[![Maintenu](https://img.shields.io/badge/maintained-yes-green.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/commits/main)
[![Activité](https://img.shields.io/github/commit-activity/y/Xaoimoon/ha-freebox?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/commits/main)

Intégration Home Assistant (non officielle) pour les Freebox. Elle dialogue en local avec la box, par l'API de Freebox OS, et affiche dans Home Assistant l'état de la connexion et de la fibre, le trafic, le contrôle parental, les appareils connectés et l'état de la box. C'est une alternative à l'intégration officielle `freebox`, plus fidèle aux Freebox récentes comme la Freebox Ultra.

## Fonctionnalités

- Connexion Internet en temps réel et dernière coupure, pour être alerté d'une panne.
- Débits montant et descendant, et volumes de données reçues et envoyées, directement utilisables dans les statistiques et les compteurs (`utility_meter`).
- Qualité de la fibre : signal et puissances optiques reçue et émise.
- Contrôle parental : couper ou rétablir Internet pour chaque profil de Freebox OS, pour une durée ou jusqu'à nouvel ordre.
- Ports Ethernet de la box : lien, vitesse et trafic de chaque port.
- État de la box : températures, ventilateur, heure de démarrage, espace disque ; redémarrage et Wi-Fi.
- Appels manqués sur la ligne fixe.
- Présence des appareils du réseau local.
- Fonctionnement 100 % local : ni compte en ligne, ni cloud.

## Installation

### Via HACS (recommandé)

[![Ouvrir le dépôt dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Xaoimoon&repository=ha-freebox&category=integration)

Cliquer sur le bouton ci-dessus, ou ajouter le dépôt à la main :

1. Dans HACS, menu **⋮ > Dépôts personnalisés**, ajouter `https://github.com/Xaoimoon/ha-freebox` avec le type **Intégration**.
2. Rechercher "Freebox OS" dans HACS, puis **Télécharger**.
3. Redémarrer Home Assistant.

HACS vous proposera ensuite automatiquement les nouvelles versions.

### Manuelle

1. Repérer le dossier de configuration de Home Assistant (celui qui contient `configuration.yaml`).
2. Y créer un dossier `custom_components` s'il n'existe pas déjà.
3. Copier le dossier `custom_components/freebox_os` de ce dépôt dedans, pour obtenir `<config>/custom_components/freebox_os/`.
4. Redémarrer Home Assistant.

## Configuration

[![Ajouter l'intégration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=freebox_os)

Cliquer sur le bouton ci-dessus, ou :

1. **Paramètres > Appareils et services > Ajouter une intégration**.
2. Chercher "Freebox OS". La Freebox est souvent déjà proposée dans les appareils découverts.
3. Garder l'adresse proposée (`mafreebox.freebox.fr`, port `80`) ou saisir l'adresse IP de la box.
4. Valider, puis **accepter la demande d'accès sur l'écran de la Freebox** (flèche de droite). Home Assistant attend jusqu'à deux minutes.
5. Dans Freebox OS (**Paramètres de la Freebox > Gestion des accès > Applications**), accorder à l'application « Home Assistant (Freebox OS) » les droits des fonctions voulues :
   - **Modification des réglages de la Freebox** : redémarrage et Wi-Fi ;
   - **Accès au gestionnaire d'appels** : appels manqués ;
   - **Accès au contrôle parental** : profils de contrôle parental.

Home Assistant Core 2026.8 ou plus récent est requis. Si l'intégration n'apparaît pas dans la recherche, consulter **Paramètres > Système > Journaux** : la cause la plus probable est une version de Home Assistant trop ancienne.

## Appareils et entités

L'intégration crée quatre types d'appareils :

- **La Freebox** (modèle, firmware, adresse MAC) :
  - **Connexion Internet** (en ligne / hors ligne) et **Dernière coupure**, avec sa fin et sa durée ;
  - **Vitesse de téléchargement** et **Vitesse d'envoi** ;
  - **Données reçues** et **Données envoyées** : les compteurs de la box, en Go ;
  - **Wi-Fi** (interrupteur), **Redémarrer** (bouton) ;
  - en diagnostic :
    - **Signal fibre**, **Puissance optique reçue** et **Puissance optique émise** (en dBm, sur la fibre uniquement) ;
    - **Démarrée le** : heure du dernier démarrage de la box ;
    - températures et ventilateur, avec les noms donnés par la box ;
    - pour chaque port Ethernet et le port SFP : **lien**, **vitesse** et **données reçues / envoyées** ;
    - **Appels manqués** et **Marquer les appels comme lus** (bouton).
- **Un appareil par disque** : espace libre de chaque partition.
- **Un appareil par profil de contrôle parental** :

  | Entité | Rôle |
  |---|---|
  | **Accès Internet** (interrupteur) | Éteint : coupe Internet jusqu'à nouvel ordre. Allumé : rétablit l'accès, jusqu'au prochain changement prévu par le planning du profil. |
  | **Mode** | Autorisé ou Bloqué, tel qu'appliqué en ce moment par la box. |
  | **Prochain changement** | Fin d'une pause, ou prochain changement du planning. |
  | **Appareils connectés** | Nombre d'appareils du profil en ligne ; la liste complète est en attribut. |
  | **Reprendre le planning** (bouton) | Annule une pause ou une autorisation manuelle. |

- **Un traceur de présence par appareil du réseau local**, désactivé par défaut. Il est activé d'office seulement si Home Assistant connaît déjà un appareil avec la même adresse MAC.

Les disques et les profils sont rattachés à l'appareil de la Freebox.

## Bon à savoir

### Contrôle parental

- Les profils se créent et se règlent dans Freebox OS (**Paramètres de la Freebox > Contrôle parental**). Il n'y a rien à configurer dans Home Assistant : chaque profil y apparaît tout seul, y compris ceux créés plus tard, sans redémarrage.
- Les horaires réguliers restent à régler dans le planning du profil, dans Freebox OS. Home Assistant sert aux exceptions : punition, devoirs, repas…
- Pour une durée, utiliser les actions **Bloquer l'accès à Internet** (`freebox_os.block_internet`) et **Autoriser l'accès à Internet** (`freebox_os.allow_internet`), qui ciblent l'interrupteur « Accès Internet » d'un ou plusieurs profils. À l'échéance, la box revient d'elle-même au planning. **Reprendre le planning** (`freebox_os.resume_schedule`) l'y ramène tout de suite.

  ```yaml
  # Couper Internet pendant le dîner
  action: freebox_os.block_internet
  target:
    entity_id: switch.alice_acces_internet
  data:
    duration: "01:00:00"
  ```

- Un profil supprimé dans Freebox OS passe en « indisponible ». Vous pouvez alors supprimer son appareil depuis sa fiche dans Home Assistant.

### Droits de l'application

Sans un droit, les entités qui en dépendent ne sont pas créées, et un avertissement l'indique dans les journaux. Après avoir accordé le droit dans Freebox OS, recharger l'intégration. Si l'application est supprimée dans Freebox OS, Home Assistant propose de refaire l'appairage.

### Redémarrage de la box

Les compteurs de la box (données reçues et envoyées, trafic des ports) et son journal de connexion repartent de zéro à chaque redémarrage. Les statistiques et les `utility_meter` de Home Assistant le gèrent : rien n'est perdu. En revanche, **Dernière coupure** ne connaît que les coupures survenues depuis le dernier démarrage, et un redémarrage n'y compte pas comme une coupure.

### Modèles de Freebox

L'intégration est développée et testée sur une Freebox Ultra (v9). Une fonction que la box ne propose pas est simplement absente : pas de capteurs fibre en ADSL/VDSL, pas de compteurs d'appels sans le droit correspondant. La domotique de la Freebox Delta (alarme, caméras) n'est pas prise en charge.

### Cohabitation avec l'intégration officielle

L'intégration peut tourner à côté de l'intégration officielle `freebox`, le temps de reporter les entités dans les tableaux de bord et les automatisations. Les deux déclarent la même adresse MAC pour la box : Home Assistant les regroupe sur un seul appareil, où chaque entité apparaît en double jusqu'à la suppression de l'intégration officielle.

## Avertissement

Projet non affilié à Free ni à Iliad. L'intégration repose sur l'API locale de Freebox OS, dont une partie n'est pas documentée et peut changer avec les mises à jour de la box.

## Pour les développeurs

Le fonctionnement de l'API, l'environnement de développement, les tests et le processus de release sont décrits dans [TECHNIQUE.md](https://github.com/Xaoimoon/ha-freebox/blob/main/TECHNIQUE.md).

## Licence

MIT — voir [LICENSE](https://github.com/Xaoimoon/ha-freebox/blob/main/LICENSE).
