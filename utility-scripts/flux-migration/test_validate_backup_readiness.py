#!/usr/bin/env python3
"""Fixture tests for the NFS backup quiescence gate."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate-backup-readiness.py")


class BackupReadinessTests(unittest.TestCase):
    def run_gate(self, *, pvcs: list[dict], pvs: list[dict], pods: list[dict]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name, items in (("pvcs", pvcs), ("pvs", pvs), ("pods", pods)):
                path = root / f"{name}.json"
                path.write_text(json.dumps({"items": items}), encoding="utf-8")
                paths[name] = path
            return subprocess.run(
                [
                    str(SCRIPT),
                    "--pvcs", str(paths["pvcs"]),
                    "--pvs", str(paths["pvs"]),
                    "--pods", str(paths["pods"]),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    @staticmethod
    def pvc(name: str, volume: str, namespace: str = "media") -> dict:
        return {"metadata": {"name": name, "namespace": namespace}, "spec": {"volumeName": volume}}

    @staticmethod
    def pod(name: str, claim: str, *, phase: str = "Running", namespace: str = "media", labels: dict | None = None) -> dict:
        return {
            "metadata": {"name": name, "namespace": namespace, "labels": labels or {}},
            "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": claim}}]},
            "status": {"phase": phase},
        }

    def test_blocks_running_consumer_of_static_nfs_volume(self) -> None:
        result = self.run_gate(
            pvcs=[self.pvc("shared", "nfs-pv")],
            pvs=[{"metadata": {"name": "nfs-pv"}, "spec": {"nfs": {"server": "storage", "path": "/data"}}}],
            pods=[self.pod("jellyfin", "shared")],
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("media/jellyfin mounts shared", result.stderr)

    def test_blocks_running_consumer_of_csi_nfs_volume(self) -> None:
        result = self.run_gate(
            pvcs=[self.pvc("shared", "nfs-pv")],
            pvs=[{"metadata": {"name": "nfs-pv"}, "spec": {"csi": {"driver": "nfs.csi.k8s.io"}}}],
            pods=[self.pod("consumer", "shared")],
        )
        self.assertEqual(result.returncode, 1)

    def test_ignores_completed_pods_and_backup_writer(self) -> None:
        result = self.run_gate(
            pvcs=[self.pvc("shared", "nfs-pv")],
            pvs=[{"metadata": {"name": "nfs-pv"}, "spec": {"nfs": {}}}],
            pods=[
                self.pod("completed", "shared", phase="Succeeded"),
                self.pod("writer", "shared", labels={"app.kubernetes.io/name": "migration-recovery-writer"}),
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NFS-backed PVCs are quiesced", result.stdout)

    def test_does_not_treat_longhorn_as_nfs(self) -> None:
        result = self.run_gate(
            pvcs=[self.pvc("config", "longhorn-pv")],
            pvs=[{"metadata": {"name": "longhorn-pv"}, "spec": {"csi": {"driver": "driver.longhorn.io"}}}],
            pods=[self.pod("app", "config")],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Discovered 0 NFS-backed PVCs", result.stdout)


if __name__ == "__main__":
    unittest.main()
