#!/usr/bin/env python3
"""Fail closed unless a replacement Longhorn PVC is recoverable."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError(f"{path} is not a Kubernetes List")
    return [item for item in value["items"] if isinstance(item, dict)]


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Longhorn health, replica count, and remote backup before cutover cleanup"
    )
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--pvc", required=True)
    parser.add_argument("--expected-replicas", required=True, type=int)
    parser.add_argument("--pvcs", required=True, type=Path)
    parser.add_argument("--pvs", required=True, type=Path)
    parser.add_argument("--volumes", required=True, type=Path)
    parser.add_argument("--replicas", required=True, type=Path)
    parser.add_argument("--backups", required=True, type=Path)
    parser.add_argument("--max-backup-age-hours", type=float, default=48)
    parser.add_argument(
        "--now",
        help="UTC timestamp used by tests/audits; defaults to the current time",
    )
    return parser.parse_args()


def find(items: list[dict[str, Any]], predicate: Any) -> dict[str, Any] | None:
    return next((item for item in items if predicate(item)), None)


def main() -> int:
    args = parse_args()
    if args.expected_replicas < 1 or args.max_backup_age_hours <= 0:
        print("ERROR: expected replicas and backup age must be positive", file=sys.stderr)
        return 1

    try:
        pvcs = load(args.pvcs)
        pvs = load(args.pvs)
        volumes = load(args.volumes)
        replicas = load(args.replicas)
        backups = load(args.backups)
        now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    pvc = find(
        pvcs,
        lambda item: (item.get("metadata") or {}).get("namespace") == args.namespace
        and (item.get("metadata") or {}).get("name") == args.pvc,
    )
    if pvc is None:
        errors.append(f"PVC {args.namespace}/{args.pvc} does not exist")
        volume_name = ""
    else:
        pvc_spec = pvc.get("spec") or {}
        if (pvc.get("status") or {}).get("phase") != "Bound":
            errors.append("PVC is not Bound")
        pv_name = pvc_spec.get("volumeName")
        pv = find(pvs, lambda item: (item.get("metadata") or {}).get("name") == pv_name)
        csi = (pv.get("spec") or {}).get("csi") if pv else {}
        csi = csi if isinstance(csi, dict) else {}
        if csi.get("driver") != "driver.longhorn.io":
            errors.append("PVC is not backed by the Longhorn CSI driver")
        volume_name = csi.get("volumeHandle") or ""
        if not volume_name:
            errors.append("Longhorn volume handle is missing")

    volume = find(volumes, lambda item: (item.get("metadata") or {}).get("name") == volume_name)
    if volume is None:
        errors.append(f"Longhorn volume {volume_name or '<unknown>'} does not exist")
    else:
        spec = volume.get("spec") or {}
        status = volume.get("status") or {}
        if status.get("robustness") != "healthy":
            errors.append(f"Longhorn volume robustness is {status.get('robustness', 'unknown')}, not healthy")
        if spec.get("numberOfReplicas") != args.expected_replicas:
            errors.append(
                f"Longhorn volume requests {spec.get('numberOfReplicas', 'unknown')} replicas, "
                f"expected {args.expected_replicas}"
            )

        running_replicas = [
            replica
            for replica in replicas
            if ((replica.get("metadata") or {}).get("labels") or {}).get("longhornvolume") == volume_name
            and (replica.get("status") or {}).get("currentState") == "running"
            and not (replica.get("spec") or {}).get("failedAt")
        ]
        if len(running_replicas) < args.expected_replicas:
            errors.append(
                f"Longhorn has {len(running_replicas)} running non-failed replicas, "
                f"expected {args.expected_replicas}"
            )

    completed_backups: list[tuple[dt.datetime, str]] = []
    for backup in backups:
        status = backup.get("status") or {}
        if status.get("volumeName") != volume_name or status.get("state") != "Completed":
            continue
        url = status.get("url") or ""
        created = status.get("backupCreatedAt") or ""
        if not url or not created:
            continue
        try:
            completed_backups.append((parse_time(created), url))
        except ValueError:
            continue

    if not completed_backups:
        errors.append("no completed remote Longhorn backup was found")
    else:
        newest_time, newest_url = max(completed_backups)
        age = now - newest_time
        if age > dt.timedelta(hours=args.max_backup_age_hours):
            errors.append(
                f"newest completed remote backup is {age.total_seconds() / 3600:.1f}h old "
                f"(limit {args.max_backup_age_hours:g}h)"
            )
        if "://" not in newest_url:
            errors.append("newest completed backup does not have a remote URL")

    if errors:
        print(f"BLOCKED: Longhorn migration gate failed for {args.namespace}/{args.pvc}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"READY: {args.namespace}/{args.pvc} -> {volume_name}; healthy with "
        f"{args.expected_replicas} replicas and a recent completed remote backup"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
