# Changelog

## 1.2.0 — 2026-07-16

### Plugins

- Ajout de `--plugin PLUGIN_JSON [PLUGIN_JSON ...]`, option répétable.
- Fusion en mémoire de bibliothèques annexes sans modifier le cœur.
- Namespace dérivé du nom de fichier pour les composants, thèmes et raccourcis.
- Références de la forme `plugin:component`, `plugin:theme` et `plugin:class`.
- Noms de fichiers générés sûrs (`plugin-{namespace}--{component}`) pour éviter les collisions avec le cœur.
- Compatibilité des raccourcis namespacés avec les préfixes responsive et d'état.
- Rejet des doublons de namespace, noms réservés, chemins non JSON et clés locales déjà namespacées.
- Surveillance des fichiers de plugins avec `--watch` et live reload.
- Intégration des plugins dans `--list-components` et `--show-component`.
- Journalisation des plugins chargés et de leur inventaire.
- Ajout des plugins d'exemple `neon.json` et `commerce.json`.
- Ajout de `examples/plugins.json` et de tests d'isolation des namespaces.

## 1.1.0 — 2026-07-16

### Bibliothèque

- `library.json` devient la bibliothèque centrale unique, résolue depuis le dossier de `build.py`.
- Suppression de l'option CLI `--library` et de la recherche à côté de `build.json`.
- Passage à 82 composants, 191 variantes, 189 raccourcis et 9 thèmes.
- Ajout de nombreux composants de layout, formulaire, données, médias, marketing et interaction.
- Ajout de scripts prêts à l'emploi : dropzone, rating, popover, cookie consent, copie, compteur, compte à rebours, retour en haut, etc.

### CSS

- Génération ouverte des margins, paddings, gaps, dimensions et positions numériques.
- Valeurs arbitraires avec la syntaxe `[valeur]`.
- Nombres décimaux, fractions, valeurs négatives et `!important`.
- Préfixes responsive `sm`, `md`, `lg`, `xl`, `2xl`.
- États `hover`, `focus`, `focus-visible`, `active`, `disabled`, `checked`, `first`, `last`, `odd`, `even` et `dark`.
- Chargement des utilitaires après le CSS des composants pour permettre les surcharges d'instance.

### Preview et productivité

- Serveur de preview intégré via `--preview`.
- URL cliquable et ouverture automatique du navigateur.
- Options `--host`, `--port`, `--no-open` et port automatique avec `--port 0`.
- Live reload avec `--preview --watch` sans modifier les fichiers HTML finaux.
- Résolution des routes propres en preview.
- Surveillance de `build.json`, des assets et de la bibliothèque centrale.
- Initialisation de projet avec `--init`.
- Catalogue CLI avec `--list-components` et `--show-component`.

### Qualité

- Version runtime 1.1.0.
- Suite portée à 10 tests.
- Ajout de `examples/productivity.json`.
