#!/usr/bin/env python3
"""Fixture tests for the Longhorn migration safety gate."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate-longhorn-migration.py")
NOW = "2026-09-12T12:00:00Z"
VOLUME = "pvc-volume-id"


class LonghornMigrationGateTests(unittest.TestCase):
    def fixtures(self) -> dict[str, list[dict]]:
        return {
            "pvcs": [{
                "metadata": {"namespace": "media", "name": "config-v2"},
                "spec": {"volumeName": "pv-v2"},
                "status": {"phase": "Bound"},
            }],
            "pvs": [{
                "metadata": {"name": "pv-v2"},
                "spec": {"csi": {"driver": "driver.longhorn.io", "volumeHandle": VOLUME}},
            }],
            "volumes": [{
                "metadata": {"name": VOLUME},
                "spec": {"numberOfReplicas": 3},
                "status": {"robustness": "healthy", "state": "attached"},
            }],
            "replicas": [
                {
                    "metadata": {"name": f"replica-{index}", "labels": {"longhornvolume": VOLUME}},
                    "spec": {"failedAt": ""},
                    "status": {"currentState": "running"},
                }
                for index in range(3)
            ],
            "backups": [{
                "metadata": {"name": "backup-good"},
                "status": {
                    "volumeName": VOLUME,
                    "state": "Completed",
                    "backupCreatedAt": "2026-09-12T11:00:00Z",
                    "url": f"nfs://storage/backups?volume={VOLUME}",
                },
            }],
        }

    def run_gate(self, fixtures: dict[str, list[dict]]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths: dict[str, Path] = {}
            for name, items in fixtures.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps({"items": items}), encoding="utf-8")
                paths[name] = path
            return subprocess.run(
                [
                    str(SCRIPT), "--namespace", "media", "--pvc", "config-v2",
                    "--expected-replicas", "3", "--now", NOW,
                    "--pvcs", str(paths["pvcs"]), "--pvs", str(paths["pvs"]),
                    "--volumes", str(paths["volumes"]), "--replicas", str(paths["replicas"]),
                    "--backups", str(paths["backups"]),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_accepts_healthy_replicated_volume_with_recent_backup(self) -> None:
        result = self.run_gate(self.fixtures())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("READY", result.stdout)

    def test_blocks_degraded_volume(self) -> None:
        fixtures = self.fixtures()
        fixtures["volumes"][0]["status"]["robustness"] = "degraded"
        result = self.run_gate(fixtures)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not healthy", result.stderr)

    def test_blocks_missing_replica(self) -> None:
        fixtures = self.fixtures()
        fixtures["replicas"].pop()
        result = self.run_gate(fixtures)
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 running non-failed replicas", result.stderr)

    def test_blocks_old_or_incomplete_backup(self) -> None:
        fixtures = self.fixtures()
        fixtures["backups"][0]["status"].update(
            {"state": "Completed", "backupCreatedAt": "2026-09-09T11:00:00Z"}
        )
        result = self.run_gate(fixtures)
        self.assertEqual(result.returncode, 1)
        self.assertIn("73.0h old", result.stderr)


if __name__ == "__main__":
    unittest.main()
