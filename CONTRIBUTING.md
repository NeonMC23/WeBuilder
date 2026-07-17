# Contributing to WeBuilder CLI

WeBuilder v1 is feature-complete. Contributions to v1 should focus on correctness, security, accessibility, documentation, compatibility, and high-quality additions to the core library. Large visual-authoring features belong to the v2 design process. You can also help by creating your own plugins.

## Development setup

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

A normal build does not require `watchdog`; it is installed for watch-mode development.

## Before submitting a change

1. Keep all source, user-facing output, examples, and documentation in English.
2. Preserve Python 3.10 compatibility.
3. Avoid browser-side framework dependencies.
4. Add or update tests for behavior changes.
5. Run the complete test suite.
6. Build the main configuration and all valid examples.
7. Confirm that all JSON files parse successfully.
8. Update `README.md` and `CHANGELOG.md` when behavior changes.

## Code conventions

- Prefer Python standard-library features for the core builder.
- Keep functions focused and use explicit validation errors.
- Preserve structured logging; do not rely only on terminal output.
- Keep generated HTML accessible and semantic.
- Attach browser behavior with `addEventListener`, never inline event attributes.
- Escape ordinary Mustache values; use triple braces only for trusted HTML.
- Keep component CSS and JavaScript isolated and deterministic.

## Core library additions

A component should define:

- a concise English `description`;
- `default_variant`;
- `required` paths where applicable;
- `accepts_children`;
- accessible HTML;
- component or variant CSS;
- optional vanilla JavaScript;
- reasonable defaults.

New interactive components require tests or a dedicated example. Avoid adding two components that solve the same problem with minor styling differences; prefer variants.

## Plugin conventions

- Name the file `{plugin-name}.json`.
- Use a lowercase, descriptive filename namespace.
- Keep local component, theme, and shortcut names unnamespaced; WeBuilder adds the namespace.
- Prefix internal CSS selectors to reduce accidental cross-plugin leakage.
- Do not assume a plugin is the only loaded extension.
- Keep plugin JavaScript scoped to the plugin component root.
- Treat plugin configuration as executable, trusted input.

## Testing commands

```bash
python -m unittest discover -s tests -v
python build.py --input build.json --output ./build
python build.py --input examples/minimal.json --output /tmp/webuilder-minimal
python build.py --input examples/events.json --output /tmp/webuilder-events
python build.py --input examples/loops-and-children.json --output /tmp/webuilder-loops
python build.py --input examples/productivity.json --output /tmp/webuilder-productivity
python build.py --input examples/plugins.json --output /tmp/webuilder-plugins \
  --plugin plugins/neon.json plugins/commerce.json
```

The intentionally invalid example must return exit code `1`:

```bash
python build.py --input examples/invalid.json --output /tmp/webuilder-invalid
```
