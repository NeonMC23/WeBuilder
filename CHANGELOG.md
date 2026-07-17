# Changelog

All notable changes to WeBuilder are documented here.

## 2.0.0 — Visual editor foundation

### GUI backend

- Added a dependency-free local editor server in `gui/server.py` using `ThreadingHTTPServer`.
- Added APIs for loading and atomically saving `build.json`, listing components and themes, running builds, returning logs, managing plugins, and managing assets.
- Added generated-site preview serving from the same origin, including clean page paths and component highlighting.
- Added plugin discovery, activation persistence, validation, and merged core/plugin catalogs.
- Added multipart asset uploads without an external framework, with size limits, safe filenames, path confinement, and configuration updates.
- Added rotating draft backups under `.webuilder/backups/`.
- Added local Host and same-origin checks for mutating requests.

### Vanilla visual editor

- Added the responsive GUI in `gui/static/` with no frontend dependency.
- Added visual metadata and page editing.
- Added searchable core and plugin component catalogs.
- Added native drag and drop for creating, reordering, and nesting components.
- Added a component inspector for variants, IDs, utilities, dynamic content, and event JSON.
- Added page and component duplication and deletion.
- Added plugin activation controls and theme catalog refresh.
- Added asset upload, preview, path copying, and deletion.
- Added embedded build preview, structured logs, selected-component highlighting, autosave, and optional live builds.
- Added undo/redo, raw JSON editing, and configuration import/export.

### CLI integration

- Added `--gui` and `--gui-port` to `build.py`.
- Preserved direct startup with `python gui/server.py`.
- Updated the engine, preview server, GUI server, and core library metadata to 2.0.0.
- Preserved v1 build, preview, watch, plugin, and output compatibility.

## 1.3.2 — Final v1 CLI release

### Internationalization

- Standardized the CLI, errors, logs, documentation, examples, component descriptions, templates, defaults, scripts, themes, plugins, tests, and generated demonstration content on English.
- Changed generated document and scaffold defaults from `lang="fr"` to `lang="en"`.
- Reworked the README as a complete English reference and support guide.

### Reliability

- Removed stale generated `.html` and `.htm` pages before a successful regeneration while preserving unknown root files.
- Added validation and copying for page-level favicon overrides.
- Refined error wording and CLI help for professional support.
- Updated the runtime, library metadata, preview server identifier, and generated assets to 1.3.2.

### Support boundary

- Declared the v1 CLI feature-complete.
- Stabilized the v1 configuration format, plugin namespace syntax, output structure, utility syntax, and development workflow.
- Reserved visual authoring and drag-and-drop capabilities for v2.

## 1.2.0

### Plugins

- Added repeatable `--plugin PLUGIN_JSON [PLUGIN_JSON ...]` support.
- Added in-memory plugin library merging without changing the core library.
- Derived component, theme, and shortcut namespaces from plugin filenames.
- Added `plugin:component`, `plugin:theme`, and `plugin:class` references.
- Added collision-safe artifact names using `plugin-{namespace}--{component}`.
- Added responsive and state prefixes for namespaced plugin shortcuts.
- Rejected duplicate namespaces, reserved names, non-JSON paths, and pre-namespaced local keys.
- Watched loaded plugin files in watch and live-reload modes.
- Integrated plugins into `--list-components` and `--show-component`.
- Added structured plugin inventory log entries.
- Added the example `neon.json` and `commerce.json` plugins.
- Added `examples/plugins.json` and plugin namespace tests.

## 1.1.0

### Core library

- Made the root `library.json` the single canonical core library.
- Removed the CLI `--library` override and project-local automatic lookup.
- Expanded the core to 82 components, 191 variants, 189 static utilities, and 9 themes.
- Added layout, form, data, media, marketing, and interaction components.
- Added ready-made scripts for dropzones, ratings, popovers, consent, clipboard copying, counters, countdowns, and navigation helpers.

### CSS

- Added open-ended numeric margin, padding, gap, sizing, and positioning utilities.
- Added arbitrary values with bracket syntax.
- Added decimals, fractions, negative values, and `!important` support.
- Added `sm`, `md`, `lg`, `xl`, and `2xl` responsive prefixes.
- Added hover, focus, active, disabled, checked, structural, and dark state prefixes.
- Loaded utilities after component CSS to allow instance-level overrides.

### Preview and productivity

- Added the integrated `--preview` server.
- Added a clickable URL and automatic browser opening.
- Added `--host`, `--port`, `--no-open`, and free-port selection.
- Added live reload with `--preview --watch` without modifying production HTML.
- Added clean preview routes.
- Added project initialization with `--init`.
- Added component discovery with `--list-components` and `--show-component`.

## 1.0.0

- Added the initial argparse CLI.
- Added multi-page HTML generation.
- Added the Mustache-compatible template renderer.
- Added component validation and structured JSON logging.
- Added separate theme, utility, and component CSS generation.
- Added vanilla JavaScript component files and declarative event listeners.
- Added asset copying with directory preservation.
- Added watchdog-based rebuild mode.
