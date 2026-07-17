from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

from gui.server import GUIHTTPServer, GUIRequestHandler, GUIState


class GUIServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary_directory.name) / "project"
        self.project.mkdir()
        self.input_path = self.project / "build.json"
        self.output_path = self.project / "build"
        self.config = {
            "meta": {"title": "GUI test", "theme": "light", "lang": "en"},
            "assets": [],
            "pages": [
                {
                    "path": "index.html",
                    "components": [
                        {
                            "type": "heading",
                            "variant": "h1",
                            "content": {"text": "Visual editor"},
                        }
                    ],
                }
            ],
        }
        self.input_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.state = GUIState(self.input_path, self.output_path)
        handler = partial(GUIRequestHandler, state=self.state)
        self.server = GUIHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def request_json(self, path: str, *, method: str = "GET", body=None, headers=None):
        data = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_static_application_and_catalog_endpoints(self) -> None:
        with urllib.request.urlopen(self.base_url + "/", timeout=5) as response:
            document = response.read().decode("utf-8")
            self.assertIn("WeBuilder Visual Editor", document)
            self.assertIn("Content-Security-Policy", response.headers)

        status = self.request_json("/api/status")
        components = self.request_json("/api/components")
        themes = self.request_json("/api/themes")
        self.assertEqual(status["status"]["version"], "2.0.0")
        self.assertGreaterEqual(len(components["components"]), 80)
        self.assertTrue(any(item["type"] == "heading" for item in components["components"]))
        self.assertTrue(any(item["name"] == "light" for item in themes["themes"]))

    def test_save_build_logs_and_preview(self) -> None:
        changed = json.loads(json.dumps(self.config))
        changed["meta"]["title"] = "Saved from GUI"
        saved = self.request_json("/api/save", method="POST", body={"config": changed})
        self.assertTrue(saved["ok"])
        self.assertEqual(json.loads(self.input_path.read_text())["meta"]["title"], "Saved from GUI")
        self.assertTrue(any((self.project / ".webuilder" / "backups").glob("build-*.json")))

        built = self.request_json("/api/build", method="POST")
        self.assertTrue(built["success"])
        self.assertGreaterEqual(built["revision"], 1)
        self.assertTrue((self.output_path / "index.html").is_file())
        self.assertTrue(any(log["message"] == "Build successful" for log in built["logs"]))

        with urllib.request.urlopen(self.base_url + "/preview/index", timeout=5) as response:
            preview = response.read().decode("utf-8")
        self.assertIn("Saved from GUI", preview)
        self.assertIn("data-webuilder-gui", preview)

    def test_plugin_activation_updates_catalog(self) -> None:
        plugins = self.request_json("/api/plugins")["plugins"]
        self.assertTrue(any(plugin["name"] == "neon" for plugin in plugins))
        payload = self.request_json(
            "/api/plugins", method="POST", body={"enabled": ["neon"]}
        )
        self.assertIn("neon", payload["enabled"])
        self.assertTrue(any(item["type"] == "neon:card" for item in payload["components"]))
        self.assertTrue(any(item["name"] == "neon:cyber" for item in payload["themes"]))

    def test_multipart_upload_and_delete_asset(self) -> None:
        boundary = "----WeBuilderTestBoundary"
        content = b"hello asset"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="hello.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            self.base_url + "/api/upload-assets?directory=docs",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            uploaded = json.load(response)
        self.assertEqual(uploaded["uploaded"], ["docs/hello.txt"])
        self.assertEqual((self.project / "assets" / "docs" / "hello.txt").read_bytes(), content)
        self.assertIn("docs/hello.txt", json.loads(self.input_path.read_text())["assets"])

        deleted = self.request_json(
            "/api/delete-asset", method="POST", body={"path": "docs/hello.txt"}
        )
        self.assertTrue(deleted["ok"])
        self.assertFalse((self.project / "assets" / "docs" / "hello.txt").exists())
        self.assertNotIn("docs/hello.txt", json.loads(self.input_path.read_text())["assets"])

    def test_untrusted_host_is_rejected_for_mutations(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps({"config": self.config})
        connection.request(
            "POST",
            "/api/save",
            body=body,
            headers={
                "Host": "attacker.example",
                "Origin": "http://attacker.example",
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode())),
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        self.assertEqual(response.status, 403)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
