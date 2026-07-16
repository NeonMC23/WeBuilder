from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from functools import partial
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("webuilder_build", ROOT / "build.py")
assert SPEC and SPEC.loader
webuilder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = webuilder
SPEC.loader.exec_module(webuilder)


class MustacheRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = webuilder.MustacheRenderer()

    def test_variables_loops_inverted_and_escaping(self) -> None:
        template = (
            "<h1>{{title}}</h1>"
            "{{#items}}<p>{{name}}={{value}}</p>{{/items}}"
            "{{^empty}}<em>vide</em>{{/empty}}"
        )
        result = self.renderer.render(
            template,
            {
                "title": "<script>",
                "items": [{"name": "A", "value": 1}, {"name": "B", "value": 2}],
                "empty": [],
            },
        )
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("<p>A=1</p><p>B=2</p>", result)
        self.assertIn("<em>vide</em>", result)

    def test_scalar_current_context_and_unescaped_value(self) -> None:
        result = self.renderer.render(
            "{{#items}}[{{.}}]{{/items}} {{{html}}}",
            {"items": ["a", "b"], "html": "<strong>ok</strong>"},
        )
        self.assertEqual(result, "[a][b] <strong>ok</strong>")

    def test_malformed_section_raises(self) -> None:
        with self.assertRaises(webuilder.TemplateError):
            self.renderer.render("{{#items}}sans fermeture", {"items": []})


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_directory.name) / "project"
        self.project.mkdir()
        shutil.copy2(ROOT / "library.json", self.project / "library.json")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def write_build(self, data: dict) -> Path:
        path = self.project / "build.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_complete_build_assets_css_js_and_multiple_pages(self) -> None:
        asset = self.project / "assets" / "images" / "logo.txt"
        asset.parent.mkdir(parents=True)
        asset.write_text("asset", encoding="utf-8")
        input_path = self.write_build(
            {
                "meta": {"title": "Test", "theme": "light", "lang": "fr"},
                "assets": ["images/logo.txt"],
                "pages": [
                    {
                        "path": "index.html",
                        "components": [
                            {
                                "type": "button",
                                "variant": "primary",
                                "id": "shared",
                                "class": [
                                    "mt-2",
                                    "mt-37",
                                    "md:hover:-mt-[3px]",
                                    "p-[clamp(1rem,_3vw,_2rem)]",
                                ],
                                "content": {"text": "Cliquer"},
                                "events": {"click": "el.dataset.clicked = 'yes';"},
                            }
                        ],
                    },
                    {
                        "path": "nested/second.html",
                        "components": [
                            {
                                "type": "button",
                                "variant": "danger",
                                "id": "shared",
                                "content": {"text": "Supprimer"},
                                "events": {"click": "console.log('second');"},
                            }
                        ],
                    },
                ],
            }
        )
        output = self.project / "site"

        success = webuilder.build_site(input_path, output, quiet=True)

        self.assertTrue(success)
        self.assertTrue((output / "index.html").is_file())
        self.assertTrue((output / "nested" / "second.html").is_file())
        self.assertEqual((output / "assets" / "images" / "logo.txt").read_text(), "asset")
        self.assertTrue((output / "css" / "button-primary.css").is_file())
        self.assertTrue((output / "css" / "button-danger.css").is_file())
        utilities_css = (output / "css" / "shortcuts.css").read_text()
        self.assertIn("margin-top: 9.25rem", utilities_css)
        self.assertIn("@media (min-width: 48rem)", utilities_css)
        self.assertIn("calc(3px * -1)", utilities_css)
        self.assertIn("padding: clamp(1rem, 3vw, 2rem)", utilities_css)
        button_js = (output / "js" / "components" / "button.js").read_text()
        self.assertIn("addEventListener", button_js)
        self.assertIn("index-html--0--shared", button_js)
        self.assertIn("nested-second-html--0--shared", button_js)
        html_text = (output / "index.html").read_text()
        self.assertRegex(html_text, r"data-id=['\"]shared['\"]")
        self.assertIn("/css/button-primary.css", html_text)
        log = json.loads((output / "log.json").read_text())
        self.assertEqual(log[-1]["level"], "info")
        self.assertEqual(log[-1]["message"], "Build successful")

    def test_validation_collects_unknown_component_required_field_and_asset(self) -> None:
        input_path = self.write_build(
            {
                "meta": {"title": "Invalid", "theme": "light"},
                "assets": ["missing.png"],
                "pages": [
                    {
                        "path": "index.html",
                        "components": [
                            {"type": "unknown", "variant": "default"},
                            {"type": "button", "variant": "primary", "content": {}},
                        ],
                    }
                ],
            }
        )
        output = self.project / "invalid-output"

        success = webuilder.build_site(input_path, output, quiet=True)

        self.assertFalse(success)
        messages = [entry["message"] for entry in json.loads((output / "log.json").read_text())]
        self.assertTrue(any("introuvable" in message and "unknown" in message for message in messages))
        self.assertTrue(any("content.text" in message for message in messages))
        self.assertTrue(any("Asset introuvable" in message for message in messages))
        self.assertFalse((output / "index.html").exists())

    def test_children_are_appended_for_legacy_template_without_placeholder(self) -> None:
        library = {
            "themes": {"light": {"css": ":root { --bg: white; --text: black; }"}},
            "shortcuts": {"class": {}},
            "components": {
                "legacy": {
                    "default_variant": "default",
                    "variants": {
                        "default": {
                            "html": "<div class='legacy'>Parent</div>",
                            "css": ".legacy {}",
                            "js": "",
                        }
                    },
                },
                "leaf": {
                    "default_variant": "default",
                    "accepts_children": False,
                    "required": ["content.text"],
                    "variants": {
                        "default": {
                            "html": "<span>{{content.text}}</span>",
                            "css": "",
                            "js": "",
                        }
                    },
                },
            },
        }
        (self.project / "library.json").write_text(json.dumps(library), encoding="utf-8")
        input_path = self.write_build(
            {
                "meta": {"title": "Legacy", "theme": "light"},
                "assets": [],
                "pages": [
                    {
                        "path": "index.html",
                        "components": [
                            {
                                "type": "legacy",
                                "children": [
                                    {"type": "leaf", "content": {"text": "Enfant"}}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        output = self.project / "legacy-output"

        self.assertTrue(
            webuilder.build_site(
                input_path,
                output,
                library_path=self.project / "library.json",
                quiet=True,
            )
        )
        document = (output / "index.html").read_text()
        self.assertIn("Parent<span", document)
        self.assertLess(document.index("Enfant"), document.index("</div>"))

    def test_unsafe_page_path_is_rejected(self) -> None:
        input_path = self.write_build(
            {
                "meta": {"title": "Unsafe", "theme": "light"},
                "assets": [],
                "pages": [{"path": "../outside.html", "components": []}],
            }
        )
        output = self.project / "unsafe-output"

        self.assertFalse(webuilder.build_site(input_path, output, quiet=True))
        log = json.loads((output / "log.json").read_text())
        self.assertTrue(any("Chemin de page" in entry["message"] for entry in log))

    def test_default_library_is_the_single_canonical_library(self) -> None:
        # A broken library next to build.json must be ignored by the normal API.
        (self.project / "library.json").write_text("{}", encoding="utf-8")
        input_path = self.write_build(
            {
                "meta": {"title": "Canonical", "theme": "light"},
                "assets": [],
                "pages": [
                    {
                        "path": "index.html",
                        "components": [
                            {
                                "type": "heading",
                                "variant": "h1",
                                "content": {"text": "Bibliothèque centrale"},
                            }
                        ],
                    }
                ],
            }
        )
        output = self.project / "canonical-output"

        self.assertTrue(webuilder.build_site(input_path, output, quiet=True))
        self.assertIn(
            "Bibliothèque centrale", (output / "index.html").read_text(encoding="utf-8")
        )


class LibraryTests(unittest.TestCase):
    def test_full_library_inventory_and_templates(self) -> None:
        library = json.loads((ROOT / "library.json").read_text(encoding="utf-8"))
        components = library["components"]
        renderer = webuilder.MustacheRenderer()
        self.assertGreaterEqual(len(components), 80)
        self.assertGreaterEqual(
            sum(len(component["variants"]) for component in components.values()), 190
        )
        self.assertGreaterEqual(len(library["shortcuts"]["class"]), 180)
        self.assertGreaterEqual(len(library["themes"]), 9)
        for component in components.values():
            for variant in component["variants"].values():
                renderer.parse(variant["html"])


class PluginTests(unittest.TestCase):
    def make_plugin(self, directory: Path, filename: str = "analytics.json") -> Path:
        plugin = {
            "version": "0.1.0",
            "themes": {
                "night": {
                    "css": ":root { --bg: #010203; --text: #fff; --primary: #0ff; }"
                }
            },
            "components": {
                "button": {
                    "description": "Plugin button intentionally colliding with core button",
                    "default_variant": "default",
                    "required": ["content.text"],
                    "accepts_children": False,
                    "variants": {
                        "default": {
                            "html": "<button class='analytics-button {{class}}'>{{content.text}}</button>",
                            "css": ".analytics-button { color: var(--primary); }",
                            "js": "document.querySelectorAll('.analytics-button').forEach((button) => button.dataset.ready = 'true');",
                        }
                    },
                }
            },
            "shortcuts": {
                "class": {"glow": "box-shadow: 0 0 20px var(--primary);"}
            },
        }
        plugin["components"]["widget"] = {
            "description": "Plugin-only widget",
            "default_variant": "default",
            "required": ["content.text"],
            "accepts_children": False,
            "variants": {
                "default": {
                    "html": "<aside class='analytics-widget {{class}}'>{{content.text}}</aside>",
                    "css": ".analytics-widget { border: 1px solid var(--primary); }",
                    "js": "",
                }
            },
        }
        path = directory / filename
        path.write_text(json.dumps(plugin), encoding="utf-8")
        return path

    def test_namespaced_components_themes_shortcuts_and_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            plugin_path = self.make_plugin(project)
            build_file = project / "build.json"
            build_file.write_text(
                json.dumps(
                    {
                        "meta": {"title": "Plugin", "theme": "analytics:night"},
                        "assets": [],
                        "pages": [
                            {
                                "path": "index.html",
                                "components": [
                                    {
                                        "type": "analytics:button",
                                        "variant": "default",
                                        "class": [
                                            "analytics:glow",
                                            "md:hover:analytics:glow",
                                        ],
                                        "content": {"text": "Plugin action"},
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = project / "output"

            self.assertTrue(
                webuilder.build_site(
                    build_file,
                    output,
                    plugin_paths=[plugin_path],
                    quiet=True,
                )
            )
            self.assertTrue(
                (output / "css" / "plugin-analytics--button-default.css").is_file()
            )
            self.assertTrue(
                (output / "js" / "components" / "plugin-analytics--button.js").is_file()
            )
            global_css = (output / "css" / "global.css").read_text()
            shortcuts_css = (output / "css" / "shortcuts.css").read_text()
            self.assertIn("--bg: #010203", global_css)
            self.assertIn("box-shadow: 0 0 20px", shortcuts_css)
            self.assertIn("@media (min-width: 48rem)", shortcuts_css)
            self.assertIn(":hover", shortcuts_css)
            log = json.loads((output / "log.json").read_text())
            self.assertEqual(log[0]["message"], "Plugin loaded")
            self.assertEqual(log[0]["plugin"], "analytics")

            # The exact same local name remains available from the core library.
            merged, _ = webuilder.load_library_with_plugins([plugin_path])
            self.assertIn("button", merged["components"])
            self.assertIn("analytics:button", merged["components"])
            self.assertNotEqual(
                webuilder._artifact_name("analytics-button"),
                webuilder._artifact_name("analytics:button"),
            )

    def test_plugin_component_requires_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            plugin_path = self.make_plugin(project, "extra.json")
            build_file = project / "build.json"
            build_file.write_text(
                json.dumps(
                    {
                        "meta": {"title": "Plugin", "theme": "light"},
                        "assets": [],
                        "pages": [
                            {
                                "path": "index.html",
                                "components": [
                                    {"type": "widget", "content": {"text": "No namespace"}}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = project / "output"
            self.assertFalse(
                webuilder.build_site(
                    build_file,
                    output,
                    plugin_paths=[plugin_path],
                    quiet=True,
                )
            )
            messages = [
                entry["message"]
                for entry in json.loads((output / "log.json").read_text())
            ]
            self.assertTrue(any("introuvable" in message for message in messages))

    def test_duplicate_plugin_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "one"
            second = root / "two"
            first.mkdir()
            second.mkdir()
            first_path = self.make_plugin(first, "duplicate.json")
            second_path = self.make_plugin(second, "duplicate.json")
            with self.assertRaises(webuilder.ConfigurationError):
                webuilder.load_library_with_plugins([first_path, second_path])


class PreviewTests(unittest.TestCase):
    def test_preview_status_clean_urls_and_live_reload_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            (output / "index.html").write_text(
                "<!doctype html><html><body>Preview</body></html>", encoding="utf-8"
            )
            state = webuilder.PreviewState(3)
            handler = partial(
                webuilder.PreviewRequestHandler,
                directory=str(output),
                preview_state=state,
            )
            server = webuilder.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                status = json.load(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/__webuilder/status", timeout=2
                    )
                )
                document = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/index", timeout=2
                ).read().decode("utf-8")
                self.assertEqual(status["version"], 3)
                self.assertIn("data-webuilder-preview", document)
                self.assertIn("Preview", document)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
