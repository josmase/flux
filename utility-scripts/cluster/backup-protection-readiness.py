#!/usr/bin/env python3
"""Fail closed before backup-schedule expansion or any backup pruning.

Run from the production kubectl context. The gate reads Kubernetes inventory,
not Secret objects or credential values. It compares live LINSTOR PVCs with
the approved T1 ownership matrix, requires a Ready RustFS v2 baseline for each
scheduled application PVC, requires plugin backup/schedule coverage for the
two approved CNPG clusters, and checks the live RustFS capacity guard.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OWNERSHIP = ROOT / "docs/LINSTOR_BACKUP_OWNERSHIP_2026-11-12.csv"
DEFERRED_OWNERS = {"Artifactory", "Artifactory PostgreSQL", "Immich"}
CNPG_CLUSTERS = {
    ("cnpg-system", "shared-postgres"),
    ("felis", "felis-postgres-ha"),
    ("gitlab", "gitlab-postgres"),
}
PLUGIN = "barman-cloud.cloudnative-pg.io"
CAPACITY_MAX_AGE_SECONDS = 600


class GateError(RuntimeError):
    pass


def kubectl_json(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise GateError(f"kubectl {' '.join(args)} failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"kubectl {' '.join(args)} returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise GateError(f"kubectl {' '.join(args)} did not return a Kubernetes List")
    return value


def linstor_schedule_rows() -> list[tuple[str, str, str]]:
    result = subprocess.run(
        [
            "kubectl", "-n", "piraeus-datastore", "exec", "deploy/linstor-controller", "--",
            "linstor", "schedule", "list-by-resource", "--active-only", "--pastable",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise GateError("LINSTOR active schedule inventory failed")
    rows: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(columns) < 3 or columns[0].lower() == "resource":
            continue
        if not re.fullmatch(r"(?:pvc-[a-f0-9-]+|[a-zA-Z0-9_.-]+)", columns[0]):
            continue
        rows.append((columns[0], columns[1], columns[2]))
    return rows


def linstor_schedule_definitions() -> dict[str, tuple[str, str, str, str, str]]:
    result = subprocess.run(
        [
            "kubectl", "-n", "piraeus-datastore", "exec", "deploy/linstor-controller", "--",
            "linstor", "schedule", "list", "--pastable",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise GateError("LINSTOR schedule definition inventory failed")
    definitions: dict[str, tuple[str, str, str, str, str]] = {}
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(columns) < 6 or columns[0].lower() == "name":
            continue
        if columns[0].startswith("linstor-standard-shard-"):
            definitions[columns[0]] = (columns[1], columns[2], columns[3], columns[4], columns[5])
        else:
            definitions[columns[0]] = (columns[1], columns[2], columns[3], columns[4], columns[5])
    return definitions


def identity(metadata: dict[str, Any]) -> tuple[str, str]:
    return str(metadata.get("namespace", "default")), str(metadata.get("name", ""))


def timestamp(value: str | None) -> dt.datetime:
    if not value:
        raise ValueError("timestamp is empty")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def owner_rows() -> dict[tuple[str, str], dict[str, str]]:
    with OWNERSHIP.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["namespace"], row["pvc"])
        if key in result:
            raise GateError(f"duplicate ownership row for {key[0]}/{key[1]}")
        result[key] = row
    return result


def scheduled_owner(row: dict[str, str]) -> bool:
    rpo = row.get("rpo_target", "")
    disposition = row.get("disposition", "").lower()
    return (
        row.get("phase") == "Bound"
        and not row.get("deletion_timestamp")
        and not rpo.upper().startswith("N/A")
        and row.get("service_owner") not in DEFERRED_OWNERS
        and not any(word in disposition for word in ("recovery-only", "retiring", "retired"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pre-schedule",
        action="store_true",
        help="check all protection prerequisites while the LINSTOR schedules are being staged",
    )
    args = parser.parse_args()
    blockers: list[str] = []
    try:
        owners = owner_rows()
        pvc_list = kubectl_json("get", "pvc", "-A")
        pv_list = kubectl_json("get", "pv")
        vss_list = kubectl_json("get", "volumesnapshots.snapshot.storage.k8s.io", "-A")
        vsc_list = kubectl_json("get", "volumesnapshotcontents.snapshot.storage.k8s.io")
        clusters_list = kubectl_json("get", "clusters.postgresql.cnpg.io", "-A")
        stores_list = kubectl_json("get", "objectstores.barmancloud.cnpg.io", "-A")
        schedules_list = kubectl_json("get", "scheduledbackups.postgresql.cnpg.io", "-A")
        backups_list = kubectl_json("get", "backups.postgresql.cnpg.io", "-A")
        cronjobs_list = kubectl_json("get", "cronjobs", "-A")
        active_linstor_schedules = linstor_schedule_rows()
        linstor_schedules = linstor_schedule_definitions()
    except (OSError, subprocess.TimeoutExpired, GateError) as exc:
        print(f"BLOCKED: inventory collection failed: {exc}", file=sys.stderr)
        return 2

    live_pvcs: dict[tuple[str, str], dict[str, Any]] = {}
    for pvc in pvc_list["items"]:
        meta = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        status = pvc.get("status") or {}
        if (
            spec.get("storageClassName") == "linstor"
            and status.get("phase") == "Bound"
            and not meta.get("deletionTimestamp")
        ):
            live_pvcs[identity(meta)] = pvc

    for key in sorted(live_pvcs):
        if key not in owners:
            blockers.append(f"live PVC {key[0]}/{key[1]} is outside the approved T1 ownership matrix")

    active_expected = {key for key, row in owners.items() if scheduled_owner(row)}
    live_expected = active_expected & live_pvcs.keys()
    for key in sorted(active_expected - live_pvcs.keys()):
        blockers.append(f"approved scheduled PVC {key[0]}/{key[1]} is absent, unbound, or terminating")

    vsc_by_ref: dict[tuple[str, str, str], dict[str, Any]] = {}
    for content in vsc_list["items"]:
        spec = content.get("spec") or {}
        ref = spec.get("volumeSnapshotRef") or {}
        if ref.get("uid"):
            vsc_by_ref[(ref.get("namespace", "default"), ref.get("name", ""), ref["uid"])] = content
    ready_snapshot_pvcs: set[tuple[str, str]] = set()
    for snap in vss_list["items"]:
        meta = snap.get("metadata") or {}
        spec = snap.get("spec") or {}
        status = snap.get("status") or {}
        source = spec.get("source") or {}
        pvc_name = source.get("persistentVolumeClaimName")
        key = (meta.get("namespace", "default"), pvc_name or "")
        if (
            pvc_name
            and key in live_expected
            and spec.get("volumeSnapshotClassName") == "linstor-snapshot-s3-v2"
            and status.get("readyToUse") is True
        ):
            content_name = status.get("boundVolumeSnapshotContentName")
            content = vsc_by_ref.get((key[0], meta.get("name", ""), meta.get("uid", "")))
            if content_name and content and content.get("metadata", {}).get("name") == content_name:
                cstatus = content.get("status") or {}
                if cstatus.get("readyToUse") is True and cstatus.get("snapshotHandle"):
                    ready_snapshot_pvcs.add(key)

    for key in sorted(live_expected):
        row = owners[key]
        if row.get("service_owner") in {"Shared PostgreSQL", "Felis PostgreSQL", "GitLab PostgreSQL"}:
            continue
        if row.get("service_owner") == "GitLab Gitaly":
            continue
        if key not in ready_snapshot_pvcs:
            blockers.append(f"scheduled PVC {key[0]}/{key[1]} has no Ready RustFS v2 baseline")

    linstor_native_owners = {"Shared PostgreSQL", "Felis PostgreSQL", "GitLab PostgreSQL", "GitLab Gitaly"}
    expected_resources: dict[str, str] = {}
    pv_by_name = {
        (item.get("metadata") or {}).get("name", ""): item
        for item in pv_list["items"]
    }
    pv_by_claim = {
        identity((item.get("spec") or {}).get("claimRef") or {}): item
        for item in pv_list["items"]
        if (item.get("spec") or {}).get("claimRef")
    }
    for key in sorted(live_expected):
        row = owners[key]
        if row.get("service_owner") in linstor_native_owners:
            continue
        pvc = live_pvcs[key]
        pv_name = ((pvc.get("spec") or {}).get("volumeName"))
        pv = pv_by_name.get(pv_name or "") or pv_by_claim.get(key)
        csi = ((pv or {}).get("spec") or {}).get("csi") or {}
        handle = csi.get("volumeHandle")
        if csi.get("driver") != "linstor.csi.linbit.com" or not handle:
            blockers.append(f"scheduled PVC {key[0]}/{key[1]} has no LINSTOR CSI resource mapping")
            continue
        expected_resources[handle] = f"{key[0]}/{key[1]}"

    active_v2 = [row for row in active_linstor_schedules if row[1] == "rustfs-linstor-backups-v2"]
    active_other = [row for row in active_linstor_schedules if row[1] != "rustfs-linstor-backups-v2"]
    expected_schedule_by_resource = {
        resource: f"linstor-standard-shard-{index % 6:02d}"
        for index, (resource, _) in enumerate(
            sorted(expected_resources.items(), key=lambda item: item[1])
        )
    }
    actual_resources = {row[0] for row in active_v2}
    unexpected = actual_resources - expected_schedule_by_resource.keys()
    missing = expected_schedule_by_resource.keys() - actual_resources
    if unexpected:
        blockers.append(f"LINSTOR RustFS v2 schedules include {len(unexpected)} unapproved resource(s)")
    if missing and not args.pre_schedule:
        blockers.append(f"LINSTOR RustFS v2 schedules are missing {len(missing)} eligible resource(s)")
    if active_other:
        blockers.append(f"LINSTOR has {len(active_other)} active backup schedule(s) to a non-v2 remote")
    seen: set[str] = set()
    for resource, remote, schedule_name in active_v2:
        if resource in seen:
            blockers.append(f"LINSTOR resource {resource} has duplicate active S3 schedules")
        seen.add(resource)
        expected_schedule = expected_schedule_by_resource.get(resource)
        if expected_schedule and schedule_name != expected_schedule:
            blockers.append(f"LINSTOR resource {resource} uses {schedule_name}; expected {expected_schedule}")
    if not args.pre_schedule:
        expected_definitions = {
            f"linstor-standard-shard-{index:02d}": (
                f"10 {3 + index * 4} * * *", "", "1", "7", "RETRY"
            )
            for index in range(6)
        }
        if set(linstor_schedules) != set(expected_definitions):
            blockers.append("LINSTOR schedule definitions do not match the six-shard approved set")
        else:
            for name, policy in expected_definitions.items():
                if linstor_schedules[name] != policy:
                    blockers.append(f"LINSTOR schedule {name} has an unapproved timing or retention policy")

    gitlab_backup_schedule = next(
        (
            item
            for item in cronjobs_list["items"]
            if (item.get("metadata") or {}).get("namespace") == "gitlab"
            and "backup" in (item.get("metadata") or {}).get("name", "").lower()
        ),
        None,
    )
    if not gitlab_backup_schedule:
        blockers.append("GitLab Gitaly lacks a GitLab Toolbox app-backup CronJob")
    else:
        spec = gitlab_backup_schedule.get("spec") or {}
        if (
            spec.get("suspend") is True
            or spec.get("schedule") != "0 */6 * * *"
            or spec.get("concurrencyPolicy") != "Forbid"
        ):
            blockers.append("GitLab Toolbox app-backup CronJob is suspended or does not meet the six-hour non-overlap policy")
        try:
            last_success = timestamp((gitlab_backup_schedule.get("status") or {}).get("lastSuccessfulTime"))
            age = (dt.datetime.now(dt.timezone.utc) - last_success).total_seconds()
        except (TypeError, ValueError):
            age = float("inf")
        if age < -120 or age > 6 * 60 * 60:
            blockers.append("GitLab Toolbox app-backup CronJob has no successful run within the six-hour RPO")

    live_clusters: dict[tuple[str, str], dict[str, Any]] = {
        identity(item.get("metadata") or {}): item for item in clusters_list["items"]
    }
    for key in sorted(set(live_clusters) - CNPG_CLUSTERS):
        blockers.append(f"live CNPG cluster {key[0]}/{key[1]} is outside the approved database schedule set")

    object_stores = {identity(item.get("metadata") or {}) for item in stores_list["items"]}
    scheduled_clusters: set[tuple[str, str]] = set()
    for key in sorted(CNPG_CLUSTERS):
        cluster = live_clusters.get(key)
        if not cluster:
            blockers.append(f"approved CNPG cluster {key[0]}/{key[1]} is absent")
            continue
        plugin = next(
            (
                entry
                for entry in (cluster.get("spec") or {}).get("plugins") or []
                if entry.get("name") == PLUGIN and entry.get("isWALArchiver") is True
            ),
            None,
        )
        store_name = ((plugin or {}).get("parameters") or {}).get("barmanObjectName")
        if not store_name or (key[0], store_name) not in object_stores:
            blockers.append(f"approved CNPG cluster {key[0]}/{key[1]} lacks its live Barman ObjectStore/WAL plugin")

    for schedule in schedules_list["items"]:
        spec = schedule.get("spec") or {}
        cluster_name = ((spec.get("cluster") or {}).get("name"))
        namespace = (schedule.get("metadata") or {}).get("namespace", "default")
        key = (namespace, cluster_name or "")
        if key not in CNPG_CLUSTERS:
            blockers.append(f"CNPG ScheduledBackup {namespace}/{(schedule.get('metadata') or {}).get('name')} targets unapproved cluster {cluster_name}")
            continue
        if spec.get("suspend") is True or spec.get("method") != "plugin" or ((spec.get("pluginConfiguration") or {}).get("name") != PLUGIN):
            blockers.append(f"CNPG ScheduledBackup {namespace}/{(schedule.get('metadata') or {}).get('name')} is suspended or not using the Barman plugin")
        scheduled_clusters.add(key)
    for key in sorted(CNPG_CLUSTERS - scheduled_clusters):
        blockers.append(f"approved CNPG cluster {key[0]}/{key[1]} has no enabled plugin ScheduledBackup")

    completed_clusters: set[tuple[str, str]] = set()
    for backup in backups_list["items"]:
        meta = backup.get("metadata") or {}
        spec = backup.get("spec") or {}
        status = backup.get("status") or {}
        key = (meta.get("namespace", "default"), (spec.get("cluster") or {}).get("name", ""))
        if key in CNPG_CLUSTERS and spec.get("method") == "plugin" and status.get("phase") == "completed":
            completed_clusters.add(key)
    for key in sorted(CNPG_CLUSTERS - completed_clusters):
        blockers.append(f"approved CNPG cluster {key[0]}/{key[1]} has no completed plugin base backup")

    capacity_job = next(
        (
            item
            for item in cronjobs_list["items"]
            if (item.get("metadata") or {}).get("namespace") == "piraeus-datastore"
            and (item.get("metadata") or {}).get("name") == "rustfs-capacity-check"
        ),
        None,
    )
    last_success = ((capacity_job or {}).get("status") or {}).get("lastSuccessfulTime")
    try:
        age = (dt.datetime.now(dt.timezone.utc) - timestamp(last_success)).total_seconds()
    except (TypeError, ValueError):
        age = float("inf")
    if age < -120 or age > CAPACITY_MAX_AGE_SECONDS:
        blockers.append("RustFS capacity CronJob has no successful run in the last 10 minutes")

    print(f"Live LINSTOR PVCs: {len(live_pvcs)}; approved scheduled claims present: {len(live_expected)}")
    print(f"Ready RustFS v2 PVC baselines: {len(ready_snapshot_pvcs)}; enabled CNPG plugin schedules: {len(scheduled_clusters)}")
    print(f"Active LINSTOR backup resources: {len(active_linstor_schedules)}; eligible LINSTOR PVCs: {len(expected_resources)}")
    if blockers:
        print(f"BLOCKED: {len(blockers)} scope/protection gate(s) failed:", file=sys.stderr)
        for blocker in blockers:
            print(f"  - {blocker}", file=sys.stderr)
        return 1
    print("PASS: live workload mapping, baseline coverage, CNPG schedules, and RustFS capacity gate are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
