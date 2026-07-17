# WeBuilder

**Version 2.0.0 — visual editor foundation**

WeBuilder is a Python static-site builder and local visual authoring environment. A declarative `build.json` becomes a complete multi-page website with HTML, component-level CSS, vanilla JavaScript, copied assets, and structured logs—without a browser-side framework.

Version 2 introduces a dependency-free web GUI for visual page composition while preserving the stable v1 CLI, JSON format, component library, plugin namespaces, utility engine, and generated output.

## Highlights

- Local visual editor served entirely by Python's standard library.
- Native drag and drop for adding, nesting, and reordering components.
- Visual metadata, page, component property, event, plugin, and asset editors.
- Embedded generated-site preview with selected-component highlighting.
- Autosave, optional live builds, undo/redo, raw JSON, and import/export.
- One canonical core library: `webuilder/library.json`.
- 82 core components and 191 core variants.
- 189 static utilities plus open-ended, on-demand CSS utilities.
- 9 bundled themes.
- Namespaced plugin libraries loaded with `--plugin`.
- Unlimited component nesting through `children`.
- Built-in Mustache renderer with variables, loops, sections, and inverted sections.
- Multi-page output.
- One CSS file per used component variant.
- One JavaScript file per interactive component type.
- Declarative events compiled to `addEventListener` calls.
- Integrated preview server, clean preview URLs, automatic browser opening, and live reload.
- Asset validation and tree-preserving copies.
- Structured JSON logs and non-zero error exit codes.
- Project scaffolding and component discovery from the CLI.
- No runtime dependency for a normal build or preview.

## Requirements

- Python 3.10 or newer.
- `watchdog` only when `--watch` is used.
- A modern browser for the generated site and preview live reload.

Install the optional watch dependency:

```bash
cd webuilder
python -m pip install -r requirements.txt
```

## Quick start

### Create a project

```bash
python build.py --init ./my-site
```

The scaffold contains no copy of the core library:

```text
my-site/
├── build.json
├── assets/
│   └── images/
└── plugins/
```

### Open the visual editor

```bash
python build.py \
  --input ./my-site/build.json \
  --output ./my-site/build \
  --gui
```

The editor opens at `http://localhost:8080/`. It can also be launched directly:

```bash
python gui/server.py --input ./my-site/build.json --output ./my-site/build
```

### Build once

```bash
python build.py \
  --input ./my-site/build.json \
  --output ./my-site/build
```

### Develop with CLI preview and live reload

```bash
python build.py \
  --input ./my-site/build.json \
  --output ./my-site/build \
  --preview \
  --watch
```

WeBuilder builds the project, starts the server in the current terminal, prints a clickable URL, and opens the browser automatically:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WeBuilder preview: http://localhost:8000/
  Output: /absolute/path/my-site/build
  Live reload: on
  Press Ctrl+C to stop.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Use `Ctrl+C` to stop the preview and watcher cleanly.

## Visual editor

The v2 GUI is a local single-page application built with HTML, CSS, and vanilla JavaScript. Its backend uses `ThreadingHTTPServer` and calls the existing Python build engine directly; it does not shell out to a second terminal or require a web framework.

### Authoring features

- Edit global title, theme, language, description, author, and favicon.
- Add, duplicate, select, rename, and delete pages.
- Search and filter the complete core and plugin component catalog.
- Drag new components into a page.
- Reorder and nest existing components with native drag and drop.
- Select a component and edit its variant, ID, utility classes, content fields, and event JSON.
- Duplicate or delete components and their nested children.
- Enable or disable discovered plugins and immediately refresh components and themes.
- Upload, preview, copy, and delete project assets.
- Edit or import the complete raw JSON configuration when needed.
- Export the current document as `build.json`.
- Undo and redo up to 60 in-memory document changes.
- Autosave drafts with atomic writes and rotating backups under `.webuilder/backups/`.
- Run builds, inspect structured logs, and display the generated page in an iframe.
- Highlight the selected component in the generated preview.
- Optionally rebuild and refresh the preview after each edit with **Live build**.

### GUI commands

```bash
# Default GUI port: 8080
python build.py --gui

# Choose another port
python build.py --gui --gui-port 9090

# Let the operating system choose a free port
python build.py --gui --gui-port 0

# Do not open the browser automatically
python build.py --gui --no-open

# Start with namespaced plugins enabled
python build.py --gui \
  --plugin plugins/neon.json plugins/commerce.json
```

The standalone server exposes the same options:

```bash
python gui/server.py --help
```

### Local GUI API

The editor backend exposes same-origin JSON endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Project paths, engine version, revision, and build status. |
| `/api/load-build` | GET | Load the current `build.json`. |
| `/api/save` | POST | Atomically save a draft configuration. |
| `/api/components` | GET | List core and enabled-plugin components. |
| `/api/themes` | GET | List core and enabled-plugin themes. |
| `/api/plugins` | GET/POST | Discover and enable or disable plugins. |
| `/api/assets` | GET | List source assets and metadata. |
| `/api/upload-assets` | POST | Upload assets and add references to `build.json`. |
| `/api/delete-asset` | POST | Delete an asset and remove its configuration reference. |
| `/api/build` | POST | Build the project and return structured logs. |
| `/api/preview` | POST | Build and return preview information. |
| `/api/logs` | GET | Return the latest `log.json` entries. |
| `/preview/{page}` | GET | Serve generated pages inside the editor. |

The server binds to `127.0.0.1` by default, rejects unsafe paths and cross-origin mutations, limits upload sizes, sanitizes filenames, and never injects editor code into generated production files.

## CLI reference

```text
python build.py [--input BUILD_JSON] [--output OUTPUT]
                [--plugin PLUGIN_JSON [PLUGIN_JSON ...]]
                [--watch] [--preview] [--gui]
                [--host HOST] [--port PORT] [--gui-port PORT] [--no-open]
                [--init DIRECTORY]
                [--list-components [QUERY]]
                [--show-component TYPE]
                [--version]
```

| Option | Default | Description |
|---|---:|---|
| `--input` | `build.json` | Path to the site configuration. |
| `--output` | `./build` | Dedicated output directory. |
| `--plugin` | none | Load one or more plugin JSON files. May be repeated. |
| `--watch` | off | Watch `build.json`, source assets, the core library, and loaded plugins. |
| `--preview` | off | Start the integrated CLI site preview server. |
| `--gui` | off | Start the v2 visual editor. |
| `--host` | `127.0.0.1` | Preview or GUI bind address. |
| `--port` | `8000` | CLI preview port. Use `0` to select a free port. |
| `--gui-port` | `8080` | Visual editor port. Use `0` to select a free port. |
| `--no-open` | off | Do not open the browser automatically. |
| `--init` | — | Create a new project scaffold. |
| `--list-components` | — | List components, optionally filtered by a query. |
| `--show-component` | — | Show a component contract and a copy-ready JSON instance. |
| `--version` | — | Print the CLI version. |

A successful one-off build returns exit code `0`. Configuration, validation, or generation failures return `1`. CLI usage and unavailable optional dependency failures return `2` where applicable.

## Core library model

WeBuilder always resolves its core library from the directory containing `build.py`:

```text
webuilder/library.json
```

A `library.json` placed beside a project `build.json` is not loaded automatically. This prevents accidental library drift between projects. Optional extensions must be passed explicitly through `--plugin`.

Core inventory:

| Resource | Count |
|---|---:|
| Components | 82 |
| Variants | 191 |
| Static utility shortcuts | 189 |
| Themes | 9 |
| Numeric and arbitrary utilities | Open-ended, generated on demand |

Bundled themes:

```text
light, dark, ocean, high-contrast, forest,
sunset, nord, corporate, pastel
```

Select a theme in `build.json`:

```json
{
  "meta": {
    "theme": "nord"
  }
}
```

## JSON Schema editor support

The repository includes Draft 2020-12 schemas for completion and diagnostics in compatible editors:

```text
schemas/build.schema.json
schemas/library.schema.json
```

The bundled configurations already declare the appropriate relative `$schema` path. WeBuilder itself performs richer runtime validation and does not require a JSON Schema package.

## `build.json`

A minimal multi-component configuration looks like this:

```json
{
  "meta": {
    "title": "My website",
    "theme": "dark",
    "lang": "en",
    "description": "Built with WeBuilder",
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
            "eyebrow": "Static site generator",
            "title": "Build a complete site from JSON",
            "text": "Components, utilities, themes, events, and assets."
          },
          "children": [
            {
              "type": "button",
              "variant": "primary",
              "id": "cta",
              "content": {"text": "Get started"},
              "events": {
                "click": "console.log('clicked', el, event);"
              }
            }
          ]
        }
      ]
    }
  ]
}
```

### Global metadata

Supported metadata includes:

- `title`
- `theme`
- `lang`
- `description`
- `author`
- `robots`
- `favicon`

A page may define its own `meta` object. Page metadata is deep-merged over global metadata.

### Pages

Each page requires a safe relative `.html` or `.htm` path:

```json
{
  "path": "account/settings.html",
  "meta": {"title": "Account settings"},
  "components": []
}
```

Absolute paths, `..` traversal, non-HTML extensions, and duplicate page paths are rejected.

### Components

A component instance can define:

- `type`: required library key.
- `variant`: optional; falls back to `default_variant`.
- `id`: optional declarative identifier exposed as `data-id`.
- `class`: string or array of classes.
- `content`: template data.
- `events`: event name to JavaScript source mapping.
- `children`: nested component instances.

The library may define component- and variant-level `defaults` and `required` paths such as `content.text`.

## Mustache templates

WeBuilder includes a dedicated Mustache-compatible renderer and does not depend on Jinja2.

| Syntax | Meaning |
|---|---|
| `{{content.title}}` | HTML-escaped variable or dotted path. |
| `{{{children}}}` | Unescaped value, used for rendered child HTML. |
| `{{& html}}` | Alternate unescaped variable syntax. |
| `{{#content.items}}...{{/content.items}}` | Truthy section or list loop. |
| `{{^content.items}}...{{/content.items}}` | Inverted section. |
| `{{.}}` | Current scalar list item. |
| `{{! comment }}` | Non-rendered comment. |

Example library component:

```json
{
  "components": {
    "menu": {
      "description": "Simple navigation menu.",
      "default_variant": "default",
      "required": ["content.items"],
      "accepts_children": false,
      "variants": {
        "default": {
          "html": "<nav class='menu {{class}}'>{{#content.items}}<a href='{{href}}'>{{text}}</a>{{/content.items}}</nav>",
          "css": ".menu { display: flex; gap: 1rem; }",
          "js": ""
        }
      }
    }
  }
}
```

Use triple braces only for trusted HTML. Ordinary variables are escaped by default.

## Component nesting

`children` accepts the same objects used at page level. Child HTML is inserted at `{{{children}}}`:

```json
{
  "type": "card",
  "variant": "elevated",
  "content": {
    "title": "Account",
    "text": "Manage your profile."
  },
  "children": [
    {
      "type": "button",
      "variant": "outline",
      "content": {"text": "Edit"}
    }
  ]
}
```

For compatibility with older templates that omit the placeholder, WeBuilder inserts child output before the final closing tag.

## Declarative JavaScript events

Events in `build.json` are emitted as `addEventListener` calls in the component JavaScript file:

```json
{
  "type": "button",
  "variant": "primary",
  "id": "save",
  "content": {"text": "Save"},
  "events": {
    "click": "el.disabled = true; console.log(event.type);"
  }
}
```

Inside event source:

- `event` is the native browser event.
- `el` is `event.currentTarget`.
- `data-wb-instance` uniquely targets the component across pages.
- no inline `onclick` or equivalent attribute is generated.

Component and variant JavaScript from the library is deduplicated and wrapped in `window.WeBuilder.ready(...)`.

## CSS generation

WeBuilder writes:

```text
css/
├── global.css
├── shortcuts.css
└── {type}-{variant}.css
```

Plugin artifacts preserve namespace boundaries:

```text
css/plugin-neon--card-default.css
js/components/plugin-neon--card.js
```

Component CSS links are emitted before `shortcuts.css`, allowing instance utility classes to override component defaults.

## Open-ended utility engine

Numeric and arbitrary utilities are discovered from component `class` fields and generated only when used.

### Spacing

One numeric unit equals `0.25rem`:

```json
"class": ["mt-37", "px-7.5", "pb-128", "-ml-3"]
```

Generated values include:

```css
.mt-37 { margin-top: 9.25rem; }
.pb-128 { padding-bottom: 32rem; }
.-ml-3 { margin-left: calc(0.75rem * -1); }
```

Supported spacing families:

```text
m, mx, my, mt, mr, mb, ml
p, px, py, pt, pr, pb, pl
gap, gap-x, gap-y
```

### Arbitrary values

Use brackets for a safe arbitrary CSS value. Underscores represent spaces:

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

Rule-breaking characters, `url(...)`, `expression(...)`, and `@import` are rejected from arbitrary values.

### Sizing and positioning

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

Open-ended families include:

```text
w, h, min-w, max-w, min-h, max-h, basis
inset, inset-x, inset-y, top, right, bottom, left
opacity, z, order, grid-cols, col-span, row-span
text, bg, border, rounded, leading, tracking
```

### Breakpoints and states

Breakpoints:

```text
sm: 40rem
md: 48rem
lg: 64rem
xl: 80rem
2xl: 96rem
```

States:

```text
hover, focus, focus-visible, active, disabled,
checked, first, last, odd, even, dark
```

Prefixes can be combined:

```json
"class": [
  "p-4",
  "md:p-10",
  "lg:hover:-mt-[3px]",
  "focus-visible:border-primary",
  "dark:bg-surface"
]
```

Prefix a utility token with `!` to add `!important`:

```json
"class": ["!mt-0", "md:!p-[2rem]"]
```

Unknown classes remain in the generated HTML, allowing component-specific custom selectors.

## Plugin system

Plugin files use the same `themes`, `components`, and `shortcuts.class` sections as the core library. They are merged in memory for the current command; no source file is modified.

### Loading plugins

Load several plugin libraries in one option:

```bash
python build.py \
  --input examples/plugins.json \
  --output ./build-plugins \
  --plugin plugins/neon.json plugins/commerce.json
```

Or repeat the option:

```bash
python build.py \
  --plugin plugins/neon.json \
  --plugin plugins/commerce.json
```

Plugin files are watched when `--watch` is enabled.

### Namespaces

The filename stem becomes the namespace:

```text
plugins/neon.json      → neon
plugins/commerce.json  → commerce
```

| Local plugin resource | Build reference |
|---|---|
| component `card` from `neon.json` | `neon:card` |
| component `card` from `commerce.json` | `commerce:card` |
| theme `cyber` from `neon.json` | `neon:cyber` |
| shortcut `glow` from `neon.json` | `neon:glow` |

Core `card`, `neon:card`, and `commerce:card` remain independent.

```json
{
  "meta": {"theme": "neon:cyber"},
  "pages": [
    {
      "path": "index.html",
      "components": [
        {
          "type": "neon:card",
          "variant": "magenta",
          "class": ["neon:glow", "md:neon:glow-strong"],
          "content": {
            "title": "Namespaced extension",
            "text": "This component comes from neon.json."
          }
        }
      ]
    }
  ]
}
```

Namespaced shortcuts support responsive and state prefixes:

```json
"class": [
  "neon:glow",
  "md:neon:glow-strong",
  "hover:commerce:sale-ring",
  "lg:hover:neon:glow"
]
```

### Plugin format

```json
{
  "name": "Example UI plugin",
  "version": "1.0.0",
  "themes": {
    "special": {
      "css": ":root { --bg: #111; --text: white; --primary: cyan; }"
    }
  },
  "components": {
    "panel": {
      "description": "Plugin panel.",
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

If this file is named `special-ui.json`, its resources are referenced as `special-ui:special`, `special-ui:panel`, and `special-ui:glow`.

WeBuilder rejects:

- non-JSON plugin paths;
- invalid or reserved namespace names;
- duplicate filename namespaces, even from different directories;
- local plugin keys that already contain `:`;
- empty plugins;
- malformed component variants or Mustache templates;
- themes without CSS;
- non-string shortcut declarations.

Every loaded plugin is recorded in `log.json` with its version, resolved path, and resource counts.

## Component discovery

List the complete core catalog:

```bash
python build.py --list-components
```

Filter it:

```bash
python build.py --list-components modal
python build.py --list-components form
```

Include plugins in discovery:

```bash
python build.py \
  --list-components card \
  --plugin plugins/neon.json plugins/commerce.json
```

Show a contract and copy-ready instance:

```bash
python build.py --show-component countdown
python build.py --show-component neon:terminal --plugin plugins/neon.json
```

## Assets

Asset paths are resolved relative to the directory containing the input `build.json`:

| Reference | Source resolution | Output |
|---|---|---|
| `images/logo.svg` | `assets/images/logo.svg`, then `images/logo.svg` | `build/assets/images/logo.svg` |
| `assets/favicon.svg` | `assets/favicon.svg` | `build/assets/favicon.svg` |

The global favicon and page-level favicon overrides are validated and copied automatically. Absolute paths and parent traversal are rejected. Output directories are created as needed, and asset directory structure is preserved.

## Preview server

The integrated server uses Python's `ThreadingHTTPServer` and adds no production dependency.

```bash
python build.py --preview
python build.py --preview --watch
python build.py --preview --watch --port 0
python build.py --preview --no-open
python build.py --preview --host 0.0.0.0 --port 8080
```

Preview features:

- clickable terminal URL;
- automatic browser opening;
- configurable host and port;
- free-port selection with `--port 0`;
- clean route resolution (`/contact` serves `contact.html`);
- no-cache HTML responses;
- live reload after successful watched builds;
- no preview code written into production HTML files.

Live reload polls the internal `/__webuilder/status` endpoint. The generation counter changes only after a successful build.

## Validation and logs

WeBuilder validates the configuration before cleaning or generating output. Checks include:

- JSON syntax and root types;
- selected theme;
- page path safety and uniqueness;
- component and variant existence;
- declared required fields;
- `class`, `id`, `events`, and `children` value types;
- event names and source types;
- used Mustache templates;
- source assets and destination collisions;
- plugin structure, namespaces, and templates.

Logs are always written to `OUTPUT/log.json` when possible:

```json
[
  {
    "timestamp": "2026-07-16T12:00:00+02:00",
    "level": "info",
    "message": "Plugin loaded",
    "plugin": "neon",
    "version": "1.0.0",
    "components": 4,
    "themes": 1,
    "shortcuts": 4
  },
  {
    "timestamp": "2026-07-16T12:00:01+02:00",
    "level": "info",
    "message": "Build successful",
    "pages": 1,
    "plugins": ["neon"]
  }
]
```

The output directory must be dedicated. WeBuilder refuses the project directory and its parents. On a successful generation, stale generated HTML pages and owned `css`, `js`, and `assets` directories are cleaned before new artifacts are written. Unrecognized files in the output root are preserved.

## Generated output

The bundled demonstration generates:

```text
build/
├── index.html
├── contact.html
├── guide.html
├── assets/
├── css/
│   ├── global.css
│   ├── shortcuts.css
│   └── {type}-{variant}.css
├── js/
│   ├── global.js
│   └── components/{type}.js
└── log.json
```

HTML uses root-relative URLs such as `/css/global.css`. Serve the output through the integrated preview or another HTTP server rather than opening the HTML file directly from disk.

## Examples

```bash
# Full bundled demonstration
python build.py --input build.json --output ./build

# Minimal build
python build.py --input examples/minimal.json --output ./build-minimal

# Events and cross-page instance isolation
python build.py --input examples/events.json --output ./build-events

# Mustache loops and nested components
python build.py --input examples/loops-and-children.json --output ./build-loops

# Open-ended utilities and interactive components
python build.py \
  --input examples/productivity.json \
  --output ./build-productivity \
  --preview

# Namespaced plugins
python build.py \
  --input examples/plugins.json \
  --output ./build-plugins \
  --plugin plugins/neon.json plugins/commerce.json \
  --preview

# Expected validation failure
python build.py --input examples/invalid.json --output ./build-invalid
```

## Tests

The test suite uses `unittest` and requires no additional test dependency:

```bash
python -m unittest discover -s tests -v
```

The suite covers Mustache parsing, multiple pages, nested components, assets, generated CSS and JavaScript, event isolation, open-ended utilities, canonical library resolution, plugin namespaces and collisions, validation, path safety, legacy template compatibility, clean preview routes, and live-reload injection.

## Project layout

```text
webuilder/
├── build.py
├── gui/
│   ├── server.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── styles.css
├── library.json
├── build.json
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── requirements.txt
├── assets/
├── examples/
├── plugins/
│   ├── neon.json
│   └── commerce.json
├── schemas/
│   ├── build.schema.json
│   └── library.schema.json
├── tests/
└── build/
```

## Security model

- Ordinary Mustache variables are HTML-escaped.
- Triple braces intentionally inject trusted raw HTML.
- `events` and library `js` fields intentionally contain executable JavaScript; build only trusted configuration and plugins.
- Arbitrary utility values reject rule-breaking syntax and remote `url(...)` values.
- Page and asset paths reject absolute paths and parent traversal.
- Plugin namespaces are validated and duplicate namespaces are rejected.
- GUI API mutations require a trusted local Host and same-origin browser request.
- GUI asset uploads are size-limited, filename-sanitized, and path-confined.
- GUI saves use atomic replacement and retain up to 20 local backups.
- The output safety check prevents source-directory cleanup.

## Troubleshooting

### `--watch` reports that watchdog is missing

```bash
python -m pip install -r requirements.txt
```

### A plugin component or theme cannot be found

Confirm that the plugin was passed to the current command and that the reference includes the filename namespace:

```text
plugins/analytics.json → analytics:component-name
```

### CSS or JavaScript returns 404 when opening an HTML file directly

Generated URLs are root-relative. Use:

```bash
python build.py --preview
```

### Port 8000 or 8080 is already in use

```bash
python build.py --preview --port 0
python build.py --gui --gui-port 0
```

### The GUI cannot save or upload

Open the GUI through the exact URL printed by the server. Mutating API requests from another origin are rejected intentionally. Confirm that `build.json` and the project `assets/` directory are writable.

### A build fails validation

Inspect the structured log:

```text
OUTPUT/log.json
```

## Version 2 status

Version 2.0.0 establishes the visual editor architecture and a functional first authoring workflow. The v1 CLI remains supported and its configuration format, core library model, plugin namespace syntax, utility syntax, and output structure remain compatible. Future v2 work can build on this foundation with richer theme design, preview-to-canvas selection, component-specific form schemas, collaborative workflows, and packaged desktop distribution.
