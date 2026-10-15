import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, patch


SCRIPT = Path(__file__).with_name("sync-qbittorrent-instance.py")
SPEC = importlib.util.spec_from_file_location("sync_qbittorrent_instance", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SyncInstancesTests(unittest.TestCase):
    @patch.object(MODULE, "request")
    def test_updates_existing_and_creates_missing_instances(self, request):
        MODULE.sync_instances(
            "http://qui:7476",
            "management-key",
            "qbit-user",
            "qbit-password",
            [
                {"name": "qBittorrent", "host": "http://qbittorrent:8080"},
                {"name": "qBittorrent-2", "host": "http://qbittorrent-2-qbittorrent:8080"},
            ],
            [{"id": 1, "name": "qBittorrent", "host": "http://old-host:8080", "category": "keep"}],
        )

        self.assertEqual(
            request.call_args_list,
            [
                call(
                    "http://qui:7476/api/instances/1",
                    "management-key",
                    method="PUT",
                    payload={
                        "name": "qBittorrent",
                        "host": "http://qbittorrent:8080",
                        "username": "qbit-user",
                        "password": "qbit-password",
                        "category": "keep",
                    },
                ),
                call(
                    "http://qui:7476/api/instances",
                    "management-key",
                    method="POST",
                    payload={
                        "name": "qBittorrent-2",
                        "host": "http://qbittorrent-2-qbittorrent:8080",
                        "username": "qbit-user",
                        "password": "qbit-password",
                    },
                ),
            ],
        )

    def test_rejects_invalid_desired_instance_list(self):
        with self.assertRaises(SystemExit):
            MODULE.sync_instances("http://qui", "key", "user", "pass", [], [])


if __name__ == "__main__":
    unittest.main()
