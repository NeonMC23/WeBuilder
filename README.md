# WeBuilder 1.2

WeBuilder transforme un fichier `build.json` en site statique complet : pages HTML, CSS par variante, JavaScript vanilla par composant, thèmes et assets.

La version 1.2 conserve **une bibliothèque centrale unique** et ajoute un **système de plugins namespacés**. Des fichiers `{plugin-name}.json` peuvent compléter les composants, variantes, scripts, thèmes et raccourcis sans modifier `library.json` et sans créer de collision entre extensions.

## Points clés

- **Un seul `library.json` central**, situé à la racine de WeBuilder, à côté de `build.py`.
- Les bibliothèques annexes sont chargées explicitement avec `--plugin` et ne modifient jamais le cœur.
- Namespaces dérivés du nom de fichier : `neon.json` expose `neon:card`, `neon:cyber` et `neon:glow`.
- Plusieurs plugins peuvent déclarer les mêmes noms locaux sans collision.
- Un projet utilisateur ne recherche jamais automatiquement un `library.json` local.
- **82 composants**, **191 variantes**, **189 raccourcis statiques** et **9 thèmes** dans le cœur, extensibles à l'exécution.
- Margins, paddings, dimensions et positions numériques générés à la demande, sans échelle finie.
- Valeurs CSS arbitraires, breakpoints et états `hover`, `focus`, etc.
- Preview locale dans le même terminal, URL affichée et navigateur ouvert automatiquement.
- Live reload lorsque `--preview` et `--watch` sont combinés.
- Routes propres en preview : `/contact` résout automatiquement `contact.html`.
- CLI de découverte : `--list-components` et `--show-component`.
- Initialisation rapide d'un projet avec `--init`.
- Pages multiples, composants imbriqués, Mustache, événements et assets.
- Journal structuré dans `build/log.json`.

## Installation

Python 3.10 ou plus récent est recommandé.

```bash
cd webuilder
python -m pip install -r requirements.txt
```

`watchdog` est requis uniquement pour `--watch`. Un build simple et la preview sans surveillance utilisent exclusivement la bibliothèque standard Python.

## Workflow recommandé

### 1. Créer un projet

```bash
python build.py --init ./mon-site
```

Cette commande crée uniquement :

```text
mon-site/
├── build.json
├── assets/
│   └── images/
└── plugins/              # bibliothèques annexes facultatives
```

Aucun `library.json` n'est copié dans le projet. Tous les builds utilisent automatiquement :

```text
webuilder/library.json
```

### 2. Développer avec preview et live reload

```bash
python build.py \
  --input ./mon-site/build.json \
  --output ./mon-site/build \
  --preview \
  --watch
```

WeBuilder construit le site, démarre le serveur dans le terminal courant, affiche une URL cliquable et ouvre le navigateur :

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WeBuilder preview: http://localhost:8000/
  Output: /chemin/mon-site/build
  Live reload: on
  Press Ctrl+C to stop.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Les changements de `build.json`, des assets sources, du `library.json` central et de chaque plugin chargé provoquent un rebuild. La page ouverte se recharge automatiquement après un build réussi.

### 3. Générer sans serveur

```bash
python build.py --input ./mon-site/build.json --output ./mon-site/build
```

## CLI

```text
python build.py [--input BUILD_JSON] [--output BUILD_DIR]
                [--plugin PLUGIN_JSON [PLUGIN_JSON ...]]
                [--watch] [--preview]
                [--host HOST] [--port PORT] [--no-open]
                [--init DIRECTORY]
                [--list-components [QUERY]]
                [--show-component TYPE]
```

| Option | Défaut | Rôle |
|---|---:|---|
| `--input` | `build.json` | Configuration du site. |
| `--output` | `./build` | Dossier généré. |
| `--plugin` | aucun | Charge une liste de `{plugin-name}.json`. Option répétable. |
| `--watch` | non | Surveille la configuration, les assets, la bibliothèque centrale et les plugins chargés. |
| `--preview` | non | Lance le serveur de preview intégré. |
| `--host` | `127.0.0.1` | Adresse d'écoute de la preview. |
| `--port` | `8000` | Port HTTP. La valeur `0` choisit automatiquement un port libre. |
| `--no-open` | non | Empêche l'ouverture automatique du navigateur. |
| `--init` | — | Initialise un projet sans dupliquer la bibliothèque. |
| `--list-components` | — | Affiche le catalogue, avec filtre facultatif. |
| `--show-component` | — | Affiche le contrat et un exemple JSON prêt à copier. |
| `--version` | — | Affiche la version de WeBuilder. |

### Preview sur un port libre

```bash
python build.py --preview --watch --port 0
```

### Preview accessible sur le réseau local

```bash
python build.py --preview --watch --host 0.0.0.0 --port 8080
```

### Preview sans ouverture automatique

```bash
python build.py --preview --no-open
```

## Découvrir la bibliothèque depuis le terminal

Liste complète :

```bash
python build.py --list-components
```

Recherche :

```bash
python build.py --list-components modal
python build.py --list-components button
python build.py --list-components formulaire
```

Documentation rapide et instance prête à copier :

```bash
python build.py --show-component countdown
```

Exemple de résultat :

```json
{
  "type": "countdown",
  "variant": "default",
  "content": {
    "datetime": "À compléter"
  }
}
```

## Système de plugins

### Charger une liste de bibliothèques annexes

`--plugin` accepte un ou plusieurs chemins et peut être répété :

```bash
python build.py \
  --input build.json \
  --output ./build \
  --plugin plugins/neon.json plugins/commerce.json
```

Syntaxe équivalente :

```bash
python build.py \
  --plugin plugins/neon.json \
  --plugin plugins/commerce.json
```

Avec preview et surveillance :

```bash
python build.py \
  --input examples/plugins.json \
  --output ./build-plugins \
  --plugin plugins/neon.json plugins/commerce.json \
  --preview --watch
```

Les fichiers de plugin chargés sont surveillés par `--watch`. Une modification provoque un rebuild et un live reload après succès.

### Règle du namespace

Le namespace est toujours dérivé du nom du fichier :

```text
plugins/neon.json      → namespace neon
plugins/commerce.json  → namespace commerce
```

Les ressources deviennent :

| Ressource locale | Référence dans `build.json` |
|---|---|
| composant `card` de `neon.json` | `neon:card` |
| composant `card` de `commerce.json` | `commerce:card` |
| thème `cyber` de `neon.json` | `neon:cyber` |
| raccourci `glow` de `neon.json` | `neon:glow` |

Ainsi, `card`, `neon:card` et `commerce:card` sont trois composants indépendants.

Les fichiers générés conservent aussi la frontière du namespace afin d'éviter une collision avec un composant du cœur nommé `neon-card` :

```text
css/plugin-neon--card-default.css
js/components/plugin-neon--card.js
```

### Référencer un composant de plugin

```json
{
  "type": "neon:card",
  "variant": "magenta",
  "class": ["neon:glow"],
  "content": {
    "title": "Extension namespacée",
    "text": "Ce composant vient de neon.json."
  },
  "children": [
    {
      "type": "neon:button",
      "variant": "cyan",
      "content": {"text": "Activer"}
    }
  ]
}
```

Les composants du cœur et de différents plugins peuvent être imbriqués librement.

### Référencer un thème de plugin

```json
{
  "meta": {
    "theme": "neon:cyber"
  }
}
```

### Référencer les classes d'un plugin

```json
{
  "class": [
    "neon:glow",
    "md:neon:glow-strong",
    "hover:commerce:sale-ring",
    "lg:hover:neon:glow"
  ]
}
```

Les préfixes responsive et d'état fonctionnent avant le namespace.

### Format d'un plugin

Un plugin reprend les sections de la bibliothèque originale :

```json
{
  "name": "Mon plugin",
  "version": "1.0.0",
  "themes": {
    "special": {
      "css": ":root { --bg: #111; --text: white; --primary: cyan; }"
    }
  },
  "components": {
    "panel": {
      "description": "Panneau du plugin",
      "default_variant": "default",
      "required": ["content.title"],
      "accepts_children": true,
      "variants": {
        "default": {
          "html": "<section class='plugin-panel {{class}}'><h2>{{content.title}}</h2>{{{children}}}</section>",
          "css": ".plugin-panel { border: 1px solid var(--primary); }",
          "js": ""
        }
      }
    }
  },
  "shortcuts": {
    "class": {
      "glow": "box-shadow: 0 0 24px var(--primary);"
    }
  }
}
```

Si ce fichier s'appelle `special-ui.json`, ses références sont :

```text
special-ui:special
special-ui:panel
special-ui:glow
```

### Validation des plugins

WeBuilder refuse :

- les fichiers dont l'extension n'est pas `.json` ;
- les noms de fichier non compatibles avec un namespace ;
- deux plugins portant le même nom de fichier, même dans des dossiers différents ;
- les noms locaux contenant déjà `:` ;
- les plugins sans composant, thème ni raccourci ;
- les raccourcis dont la déclaration n'est pas une chaîne CSS ;
- les noms réservés pouvant entrer en conflit avec les préfixes (`core`, `dark`, `sm`, `md`, etc.).

La fusion est effectuée en mémoire. Ni `library.json` ni les fichiers de plugins ne sont modifiés.

### Catalogue avec plugins

```bash
python build.py \
  --list-components card \
  --plugin plugins/neon.json plugins/commerce.json

python build.py \
  --show-component neon:terminal \
  --plugin plugins/neon.json
```

Les chargements sont consignés dans `build/log.json` avec le nom, la version, le chemin et le nombre de ressources ajoutées.

## Utilitaires CSS ouverts

Le moteur ne dépend plus d'une liste finie pour les espacements. Il analyse les classes présentes dans `build.json` et écrit uniquement les règles nécessaires dans `build/css/shortcuts.css`.

Les feuilles de raccourcis sont chargées après les feuilles des composants afin que les classes ajoutées à une instance puissent surcharger les valeurs par défaut.

### Margins et paddings numériques

Une unité vaut `0.25rem` :

```json
"class": ["mt-37", "px-7.5", "pb-128", "-ml-3"]
```

Résultat :

```css
.mt-37 { margin-top: 9.25rem; }
.px-7\2e 5 { padding-inline: 1.875rem; }
.pb-128 { padding-bottom: 32rem; }
.-ml-3 { margin-left: calc(0.75rem * -1); }
```

Préfixes supportés :

```text
m, mx, my, mt, mr, mb, ml
p, px, py, pt, pr, pb, pl
gap, gap-x, gap-y
```

Les valeurs numériques entières et décimales ne sont pas limitées.

### Valeurs arbitraires

La syntaxe entre crochets accepte une valeur CSS sûre. Les espaces sont représentés par `_` :

```json
"class": [
  "mt-[13px]",
  "px-[clamp(1rem,_5vw,_6rem)]",
  "w-[42.5rem]",
  "max-w-[78ch]",
  "text-[1.35rem]",
  "bg-[#1e293b]",
  "rounded-[22px]"
]
```

### Dimensions et positions

```json
"class": [
  "w-72",
  "w-2/3",
  "min-h-screen",
  "max-w-prose",
  "top-17",
  "-left-[3px]",
  "z-137",
  "grid-cols-7",
  "col-span-3",
  "opacity-83"
]
```

Utilitaires ouverts disponibles :

```text
w, h, min-w, max-w, min-h, max-h, basis
inset, inset-x, inset-y, top, right, bottom, left
opacity, z, order, grid-cols, col-span, row-span
text, bg, border, rounded, leading, tracking
```

### Responsive et états

Breakpoints :

```text
sm: 40rem
md: 48rem
lg: 64rem
xl: 80rem
2xl: 96rem
```

États :

```text
hover, focus, focus-visible, active, disabled,
checked, first, last, odd, even, dark
```

Les préfixes sont combinables :

```json
"class": [
  "p-4",
  "md:p-10",
  "lg:hover:-mt-[3px]",
  "focus-visible:border-primary",
  "dark:bg-surface"
]
```

Le préfixe `!` force `!important` :

```json
"class": ["!mt-0", "md:!p-[2rem]"]
```

Les classes non reconnues sont conservées dans le HTML. Elles peuvent donc toujours cibler une feuille CSS personnalisée définie dans un composant.

## Bibliothèque centrale

Statistiques du cœur de la version 1.2 (hors plugins chargés à l'exécution) :

| Ressource | Quantité |
|---|---:|
| Composants | 82 |
| Variantes | 191 |
| Raccourcis statiques | 189 |
| Thèmes | 9 |
| Utilitaires numériques/arbitraires | Génération ouverte |

### Catégories principales

- **Structure** : `main`, `container`, `section`, `stack`, `cluster`, `grid`, `sidebar-layout`, `aspect-box`, `surface`, `spacer`.
- **Navigation** : `header`, `navbar`, `breadcrumb`, `pagination`, `dropdown`, `skip-link`, `footer`.
- **Typographie** : `heading`, `text`, `quote`, `code-block`, `kbd`, `divider`.
- **Contenu** : `hero`, `card`, `feature`, `banner`, `callout`, `details`, `list`, `table`, `data-list`, `timeline`, `steps`, `empty-state`.
- **Actions et statuts** : `button`, `link`, `alert`, `badge`, `status-dot`, `progress`, `meter`, `spinner`, `skeleton`, `toast`, `floating-action`, `back-to-top`.
- **Formulaires** : `form`, `input`, `textarea`, `select`, `checkbox`, `radio-group`, `switch`, `range`, `file-dropzone`, `search-bar`, `rating`.
- **Interactions** : `modal`, `drawer`, `popover`, `tooltip`, `accordion`, `tabs`, `cookie-banner`, `copy-button`.
- **Médias** : `avatar`, `image`, `video`, `audio`, `iframe`, `gallery`, `carousel`.
- **Marketing** : `stats`, `counter`, `countdown`, `pricing`, `testimonial`, `logo-cloud`, `team-grid`, `social-links`, `marquee`.

### Thèmes

```text
light, dark, ocean, high-contrast, forest,
sunset, nord, corporate, pastel
```

Le thème est sélectionné dans `meta.theme` :

```json
{
  "meta": {
    "theme": "nord"
  }
}
```

## Format de `build.json`

```json
{
  "meta": {
    "title": "Mon site",
    "theme": "dark",
    "lang": "fr",
    "description": "Description du site",
    "favicon": "assets/favicon.svg"
  },
  "assets": [
    "images/logo.svg",
    "assets/favicon.svg"
  ],
  "pages": [
    {
      "path": "index.html",
      "components": [
        {
          "type": "hero",
          "variant": "centered",
          "class": ["py-24", "md:py-32"],
          "content": {
            "title": "Un site produit rapidement",
            "text": "Composants, utilitaires ouverts et preview intégrée."
          },
          "children": [
            {
              "type": "button",
              "variant": "primary",
              "id": "cta",
              "content": {"text": "Commencer"},
              "events": {
                "click": "console.log('clic', el, event);"
              }
            }
          ]
        }
      ]
    }
  ]
}
```

## Mustache et composants enfants

Syntaxes prises en charge :

| Syntaxe | Fonction |
|---|---|
| `{{content.title}}` | Variable HTML échappée. |
| `{{{children}}}` | HTML non échappé. |
| `{{& html}}` | Valeur non échappée. |
| `{{#content.items}}...{{/content.items}}` | Section ou boucle. |
| `{{^content.items}}...{{/content.items}}` | Section inversée. |
| `{{.}}` | Élément scalaire courant. |
| `{{! commentaire }}` | Commentaire. |

Les enfants sont rendus dans `{{{children}}}`. Pour les anciens templates sans placeholder, WeBuilder les insère avant la dernière balise fermante.

## Événements JavaScript

Les événements de `build.json` deviennent des listeners dans `build/js/components/{type}.js` :

```json
{
  "type": "button",
  "variant": "primary",
  "id": "save",
  "content": {"text": "Enregistrer"},
  "events": {
    "click": "el.disabled = true; console.log(event.type);"
  }
}
```

Dans le code événementiel :

- `event` désigne l'événement natif ;
- `el` désigne `event.currentTarget` ;
- `data-wb-instance` assure un ciblage unique entre les pages ;
- aucun `onclick` n'est écrit dans le HTML.

La bibliothèque contient également des scripts prêts à l'emploi pour les modales, drawers, accordéons, onglets, carrousels, dropzones, ratings, popovers, consentement, copie, compteurs, comptes à rebours et autres composants interactifs.

## Assets

Les références sont résolues par rapport au dossier du `build.json` :

| Référence | Source | Destination |
|---|---|---|
| `images/logo.svg` | `assets/images/logo.svg`, puis `images/logo.svg` | `build/assets/images/logo.svg` |
| `assets/favicon.svg` | `assets/favicon.svg` | `build/assets/favicon.svg` |

Le favicon est automatiquement validé et copié. Les chemins absolus et les traversées `../` sont refusés.

## Preview intégrée

Le serveur est basé sur `ThreadingHTTPServer` de Python et ne demande aucune dépendance externe.

Fonctions disponibles :

- URL cliquable affichée dans le terminal ;
- ouverture automatique du navigateur ;
- port configurable ou attribution automatique avec `--port 0` ;
- routes propres ;
- désactivation du cache HTML ;
- injection du live reload uniquement dans la réponse HTTP ;
- aucun script de preview ajouté aux fichiers finaux ;
- arrêt propre avec `Ctrl+C`.

Le live reload interroge un endpoint interne `/__webuilder/status`. Le compteur de génération n'est incrémenté qu'après un build réussi.

## Validation et logs

WeBuilder vérifie notamment :

- la syntaxe JSON ;
- le thème central ;
- les chemins et doublons de pages ;
- les composants et variantes ;
- les champs `required` ;
- `class`, `children`, `events` et `id` ;
- les templates Mustache utilisés ;
- les assets et leurs destinations.

Les résultats sont écrits dans `build/log.json` :

```json
[
  {
    "timestamp": "2026-07-16T12:00:00+02:00",
    "level": "info",
    "message": "Build successful",
    "pages": 3
  }
]
```

## Exemples

```bash
python build.py --input examples/minimal.json --output ./build-minimal
python build.py --input examples/events.json --output ./build-events
python build.py --input examples/loops-and-children.json --output ./build-loops
python build.py --input examples/productivity.json --output ./build-productivity --preview
python build.py --input examples/plugins.json --output ./build-plugins \
  --plugin plugins/neon.json plugins/commerce.json --preview
```

Exemple volontairement invalide :

```bash
python build.py --input examples/invalid.json --output ./build-invalid
```

## Tests

```bash
python -m unittest discover -s tests -v
```

Les 13 tests vérifient le moteur Mustache, les pages multiples, les assets, le CSS et le JavaScript, le ciblage des événements, les utilitaires ouverts, la preview, la bibliothèque centrale, le chargement et l'isolation des plugins, les doublons de namespace, la validation, les chemins sûrs et la compatibilité avec les anciens templates.

## Structure

```text
webuilder/
├── build.py                 # CLI, builder, watch et preview
├── library.json             # bibliothèque centrale unique
├── build.json               # démonstration principale
├── README.md
├── requirements.txt
├── assets/
├── examples/
├── plugins/
│   ├── neon.json            # plugin exemple
│   └── commerce.json        # plugin exemple avec noms locaux concurrents
├── tests/
└── build/                   # résultat de la démonstration
```

## Suite envisagée

Une interface visuelle avec drag-and-drop et navigateur d'assets est une évolution cohérente. Elle n'est volontairement pas incluse dans cette étape : la priorité actuelle reste une base CLI rapide, découvrable, extensible et stable. Les contrats de composants centralisés et les identifiants d'instance constituent déjà les fondations nécessaires à un futur éditeur visuel.
