from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cut_workbench.capabilities import CapabilityRequest, RoutingPolicy
from cut_workbench.local_providers import JsonCommandProvider


class LocalProviderTests(unittest.TestCase):
    def test_json_command_adapter_makes_local_models_replaceable(self) -> None:
        code = (
            "import json,sys; r=json.load(sys.stdin); "
            "json.dump({'payload': {'language': 'zh', 'capability': r['capability']}, "
            "'evidence': [r['inputs']['media_path']]}, sys.stdout)"
        )
        provider = JsonCommandProvider(
            provider_id="local:whisper-sidecar",
            capabilities=["audio.transcribe.words"],
            command=[sys.executable, "-c", code],
        )
        result = provider.execute(
            CapabilityRequest(capability="audio.transcribe.words", inputs={"media_path": "speech.wav"})
        )
        self.assertEqual("zh", result.payload["language"])
        self.assertEqual(["speech.wav"], result.evidence)

    def test_routing_policy_loads_from_portable_json(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "routing.json"
            path.write_text(json.dumps({"default_route": "agent", "rules": {
                "video.detect.scenes": {"standard": "local", "high": "agent"}
            }}), encoding="utf-8")
            policy = RoutingPolicy.from_file(path)
            standard = CapabilityRequest(capability="video.detect.scenes", inputs={}, quality="standard")
            high = CapabilityRequest(capability="video.detect.scenes", inputs={}, quality="high")
            self.assertEqual("local", policy.route(standard, local_available=True))
            self.assertEqual("agent", policy.route(high, local_available=True))


if __name__ == "__main__":
    unittest.main()
