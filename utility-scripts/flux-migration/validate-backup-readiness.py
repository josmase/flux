#!/usr/bin/env python3
"""Verify NFS-backed PVCs are quiesced before a full filesystem copy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError(f"{path} is not a Kubernetes List")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pvcs", required=True, type=Path)
    parser.add_argument("--pvs", required=True, type=Path)
    parser.add_argument("--pods", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        pvc_list = load(args.pvcs)
        pv_list = load(args.pvs)
        pod_list = load(args.pods)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    nfs_pvs: set[str] = set()
    for pv in pv_list["items"]:
        if not isinstance(pv, dict):
            continue
        spec = pv.get("spec") or {}
        csi = spec.get("csi") or {}
        if "nfs" in spec or csi.get("driver") == "nfs.csi.k8s.io":
            name = (pv.get("metadata") or {}).get("name")
            if name:
                nfs_pvs.add(name)

    nfs_claims: set[tuple[str, str]] = set()
    for pvc in pvc_list["items"]:
        if not isinstance(pvc, dict):
            continue
        metadata = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        namespace = metadata.get("namespace") or "default"
        name = metadata.get("name")
        if not name:
            continue
        if spec.get("volumeName") in nfs_pvs:
            nfs_claims.add((namespace, name))

    active_consumers: list[str] = []
    for pod in pod_list["items"]:
        if not isinstance(pod, dict):
            continue
        metadata = pod.get("metadata") or {}
        labels = metadata.get("labels") or {}
        if labels.get("app.kubernetes.io/name") == "migration-recovery-writer":
            continue
        if (pod.get("status") or {}).get("phase") not in {"Pending", "Running"}:
            continue
        namespace = metadata.get("namespace") or "default"
        claims = []
        for volume in (pod.get("spec") or {}).get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            claim = volume.get("persistentVolumeClaim") or {}
            claim_name = claim.get("claimName") if isinstance(claim, dict) else None
            if claim_name and (namespace, claim_name) in nfs_claims:
                claims.append(claim_name)
        if claims:
            active_consumers.append(
                f"{namespace}/{metadata.get('name', '<unknown>')} mounts {','.join(sorted(claims))}"
            )

    print(f"Discovered {len(nfs_claims)} NFS-backed PVCs")
    if active_consumers:
        print("ERROR: NFS data is not quiesced; active consumers remain:", file=sys.stderr)
        for consumer in sorted(active_consumers):
            print(f"  - {consumer}", file=sys.stderr)
        return 1
    print("NFS-backed PVCs are quiesced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
