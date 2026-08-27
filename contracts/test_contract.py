import json
import unittest
from pathlib import Path


class ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(Path(__file__).with_name("openapi.json").read_text())

    def test_is_openapi_31(self) -> None:
        self.assertEqual(self.contract["openapi"], "3.1.0")
        self.assertEqual(self.contract["info"]["title"], "Robots Center Agent Communication API")

    def test_sdk_surface_is_present(self) -> None:
        paths = self.contract["paths"]
        required = {
            "/api/v1/agent_tokens": {"post"},
            "/api/v1/agents": {"get"},
            "/api/v1/agents/me": {"get", "patch"},
            "/api/v1/messages": {"get", "post"},
            "/api/v1/tasks": {"get", "post"},
            "/api/v1/groups": {"get", "post"},
            "/api/v1/socket_tokens": {"post"},
        }
        for path, methods in required.items():
            self.assertTrue(methods.issubset(paths[path]), path)

    def test_realtime_manifest(self) -> None:
        manifest = json.loads(Path(__file__).with_name("realtime.json").read_text())
        self.assertEqual(manifest["protocol"]["version"], "2.0")
        self.assertEqual(manifest["limits"]["max_frame_bytes"], 65_536)
        self.assertEqual(manifest["limits"]["agent_heartbeat_interval_seconds"], 20)

    def test_protected_operations_declare_scopes(self) -> None:
        for path, operations in self.contract["paths"].items():
            for method, operation in operations.items():
                if operation.get("security"):
                    self.assertTrue(operation.get("x-required-scopes"), f"{method} {path}")


if __name__ == "__main__":
    unittest.main()
