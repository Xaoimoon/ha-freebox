# Freebox OS pour Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/docs/faq/custom_repositories)
[![Licence](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/blob/main/LICENSE)
[![Statut](https://img.shields.io/badge/statut-en%20d%C3%A9veloppement-yellow.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/commits/main)

Intégration Home Assistant (non officielle) pour les Freebox, construite sur l'API
Freebox OS actuelle. Elle vise à remplacer l'intégration officielle `freebox`, qui suit mal
les versions récentes de Freebox OS : par exemple, sur une Freebox Ultra (v9), l'API
domotique `home/*` n'existe pas et l'intégration officielle le signale à tort comme un
problème de permission.

> **En développement.** La première version reprend les entités de l'intégration officielle ;
> les fonctions propres à cette intégration arrivent ensuite (voir les objectifs).

## Fonctionnalités

Un appareil pour la Freebox, avec :

- **connexion Internet** (en ligne / hors ligne) et **dernière coupure** (début, fin et durée,
  depuis le démarrage de la box), pour être alerté d'une panne ;
- sur la fibre : **signal fibre** et **puissances optiques reçue et émise** (dBm, diagnostic), pour
  repérer une fibre qui se dégrade (côté abonné, la puissance reçue doit rester entre -8 et -27 dBm) ;
- **démarrée le** : heure du dernier démarrage de la box (diagnostic), pour repérer ses redémarrages ;
- **ports du switch** (diagnostic), pour chaque port Ethernet et le port SFP LAN : lien (mode négocié
  et erreurs en attributs), vitesse en Mbit/s, données reçues et envoyées par la box sur le port
  (compteurs `total_increasing`) ;
- débits montant et descendant (ko/s) ;
- **volumes de données reçues et envoyées** : les compteurs cumulés de la box (en Go, état
  `total_increasing`), utilisables directement par les `utility_meter` et les statistiques ;
- températures et ventilateurs annoncés par la box (diagnostic) ;
- appels manqués non lus, et un bouton pour marquer le journal d'appels comme lu ;
- un bouton de redémarrage et un interrupteur pour le Wi-Fi de la box ;
- le suivi de la box elle-même (connexion, IPv4/IPv6, uptime en attributs).

Un appareil par disque, avec l'espace libre de chaque partition.

### Contrôle parental

Chaque profil créé dans Freebox OS (**Paramètres de la Freebox > Contrôle parental**) devient
un appareil dans Home Assistant, sans rien configurer : un profil ajouté plus tard apparaît tout
seul, un profil supprimé peut ensuite être retiré de Home Assistant. Pour chaque profil :

| Entité | Rôle |
|---|---|
| **Accès Internet** (interrupteur) | Éteint : coupe Internet jusqu'à nouvel ordre. Allumé : rétablit l'accès, jusqu'au prochain changement prévu par le planning du profil. |
| **Mode** | Autorisé ou Bloqué, tel qu'appliqué en ce moment par la box. |
| **Prochain changement** | Fin d'une pause, ou prochain changement du planning. |
| **Appareils connectés** | Nombre d'appareils du profil en ligne ; la liste complète est en attribut. |
| **Reprendre le planning** (bouton) | Annule une pause ou une autorisation manuelle. |

Pour une durée, les actions **`freebox_os.block_internet`** et **`freebox_os.allow_internet`**
acceptent un champ `duration` ; **`freebox_os.resume_schedule`** rend la main au planning. Elles
ciblent l'interrupteur « Accès Internet » d'un ou plusieurs profils :

```yaml
# Couper Internet pendant le dîner
action: freebox_os.block_internet
target:
  entity_id: switch.alice_acces_internet
data:
  duration: "01:00:00"
```

Les horaires réguliers restent à régler dans le planning du profil, dans Freebox OS : Home
Assistant sert aux exceptions (punition, devoirs, repas…).

### Présence

Un traceur de présence (`device_tracker`) par appareil vu sur le réseau local, désactivé par
défaut sauf si Home Assistant connaît déjà un appareil avec la même adresse MAC.

## Objectifs

- Appairage par jeton d'application, validé sur l'écran de la Freebox.
- Connexion Internet : état, débits, et **compteurs de trafic cumulés** directement utilisables
  par le tableau de bord Énergie et les `utility_meter`, sans calcul intermédiaire.
- Wi-Fi, appareils connectés (présence), stockage, et le reste de l'API selon le modèle de Freebox.
- Détection des fonctions absentes selon le modèle (Ultra, Delta, Pop…) : une fonction que la
  Freebox ne propose pas est ignorée, pas signalée comme une erreur.
- Fonctionnement en local uniquement (`local_polling`), sans compte en ligne.

## Configuration

1. **Paramètres > Appareils et services > Ajouter une intégration**, choisir **Freebox OS**
   (la Freebox est aussi découverte automatiquement sur le réseau local).
2. Garder l'hôte `mafreebox.freebox.fr` et le port `80`, ou saisir l'adresse IP de la box.
3. Valider, puis accepter la demande d'accès **sur l'écran de la Freebox** (flèche de droite).
4. Dans Freebox OS (**Paramètres de la Freebox > Gestion des accès > Applications**), accorder à
   l'application « Home Assistant (Freebox OS) » :
   - **Modification des réglages de la Freebox** : redémarrage et Wi-Fi ;
   - **Accès au gestionnaire d'appels** : journal d'appels ;
   - **Accès au contrôle parental** : profils de contrôle parental.

   Sans ces droits, les entités concernées ne sont pas créées.

Si l'application est révoquée dans Freebox OS, Home Assistant propose de refaire l'appairage.

## Cohabitation avec l'intégration officielle

Le domaine de cette intégration est **`freebox_os`** : elle peut être installée à côté de
l'intégration officielle `freebox`, le temps de reporter les entités utilisées par les
tableaux de bord et les automations, avant de supprimer l'officielle.

## Installation

### Via HACS

1. Dans HACS, menu **⋮ > Dépôts personnalisés**, ajouter `https://github.com/Xaoimoon/ha-freebox`
   avec le type **Intégration**.
2. Rechercher « Freebox OS » dans HACS, puis **Télécharger**.
3. Redémarrer Home Assistant.

### Manuelle

Copier le dossier `custom_components/freebox_os` de ce dépôt dans le dossier
`custom_components` de la configuration de Home Assistant, puis redémarrer.

Home Assistant Core 2026.8 ou plus récent est requis.

## Développement

Le dépôt principal est sur [brokk](https://brokk.xaoimoon.fr/xaoimoon/ha-freebox) ; GitHub
en est une copie, utilisée par HACS.

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

Les notes sur l'API Freebox OS sont dans [TECHNIQUE.md](TECHNIQUE.md).

### Versions et releases

Les versions sont calculées automatiquement à partir des messages de commit
([Conventional Commits](https://www.conventionalcommits.org/fr/)) par le workflow
`.forgejo/workflows/release.yml`, à chaque push sur `main` :

- `fix: …` ou `perf: …` → version corrective (0.1.**1**) ;
- `feat: …` → nouvelle fonctionnalité (0.**2**.0) ;
- `feat!: …` ou un pied de commit `BREAKING CHANGE:` → version majeure (**1**.0.0) ;
- les autres types (`docs`, `chore`, `refactor`, `test`, `ci`…) ne déclenchent pas de release.

Le workflow met à jour `manifest.json`, crée le tag et la release sur brokk ; la copie
GitHub transforme ensuite le tag en release GitHub (`.github/workflows/release.yml`),
que HACS propose comme mise à jour.

## Licence

[MIT](LICENSE)
