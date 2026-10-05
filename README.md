# Freebox OS pour Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/docs/faq/custom_repositories)
[![Licence](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/blob/main/LICENSE)
[![Statut](https://img.shields.io/badge/statut-en%20d%C3%A9veloppement-yellow.svg?style=for-the-badge)](https://github.com/Xaoimoon/ha-freebox/commits/main)

Intégration Home Assistant (non officielle) pour les Freebox, construite sur l'API
Freebox OS actuelle. Elle vise à remplacer l'intégration officielle `freebox`, qui suit mal
les versions récentes de Freebox OS : par exemple, sur une Freebox Ultra (v9), l'API
domotique `home/*` n'existe pas et l'intégration officielle le signale à tort comme un
problème de permission.

> **En développement : l'intégration n'est pas encore installable.** Ce dépôt ne contient
> pour l'instant que le squelette (manifeste, outillage de release, tests).

## Objectifs

- Appairage par jeton d'application, validé sur l'écran de la Freebox.
- Connexion Internet : état, débits, et **compteurs de trafic cumulés** directement utilisables
  par le tableau de bord Énergie et les `utility_meter`, sans calcul intermédiaire.
- Wi-Fi, appareils connectés (présence), stockage, et le reste de l'API selon le modèle de Freebox.
- Détection des fonctions absentes selon le modèle (Ultra, Delta, Pop…) : une fonction que la
  Freebox ne propose pas est ignorée, pas signalée comme une erreur.
- Fonctionnement en local uniquement (`local_polling`), sans compte en ligne.

## Cohabitation avec l'intégration officielle

Le domaine de cette intégration est **`freebox_os`** : elle peut être installée à côté de
l'intégration officielle `freebox`, le temps de reporter les entités utilisées par les
tableaux de bord et les automations, avant de supprimer l'officielle.

## Installation (quand une première version sera publiée)

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
