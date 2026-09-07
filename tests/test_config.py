from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.config import load_runtime_config, load_vectcut_config
from cut_workbench.errors import ValidationError


class RuntimeConfigTests(unittest.TestCase):
    def test_vectcut_only_config_preserves_default_ffprobe_provider(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            path.write_text(json.dumps({"vectcut": {"draft_folder": "D:/Jianying/Drafts"}}), encoding="utf-8")

            registry, _ = load_runtime_config(path)

        self.assertEqual([{"provider_id": "local:ffprobe"}], registry.describe())

    def test_explicit_ffprobe_replaces_the_default_executable(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            path.write_text(json.dumps({"providers": [{"kind": "ffprobe", "executable": "D:/tools/ffprobe.exe"}]}), encoding="utf-8")

            registry, _ = load_runtime_config(path)

        self.assertEqual([{"provider_id": "local:ffprobe"}], registry.describe())
        provider = registry.find("media.probe")
        self.assertEqual("D:/tools/ffprobe.exe", provider.executable)

    def test_vectcut_endpoint_must_remain_local(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            path.write_text(json.dumps({"vectcut": {"base_url": "https://open.vectcut.com"}}), encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "local loopback"):
                load_vectcut_config(path)

    def test_localhost_endpoint_is_accepted(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            path.write_text(json.dumps({"vectcut": {"base_url": "http://localhost:9100"}}), encoding="utf-8")

            config = load_vectcut_config(path)

        self.assertEqual("http://localhost:9100", config["base_url"])

    def test_invalid_local_port_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            path.write_text(json.dumps({"vectcut": {"base_url": "http://127.0.0.1:not-a-port"}}), encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "valid port"):
                load_vectcut_config(path)


if __name__ == "__main__":
    unittest.main()
