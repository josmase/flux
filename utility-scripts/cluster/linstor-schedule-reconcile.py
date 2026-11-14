#!/usr/bin/env python3
"""Plan or safely reconcile the approved LINSTOR-to-RustFS schedules.

The default mode is read-only. `--apply` requires every protection prerequisite
to pass, a current live-to-plan PVC/resource mapping, healthy LINSTOR thin
resources, and resolved application-specific consistency gates. It enables
the schedule only on explicitly listed resource definitions; it never enables
a controller-wide or resource-group schedule.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/LINSTOR_T5_2_SCHEDULE_PLAN_2026-11-14.csv"
GATE = ROOT / "utility-scripts/cluster/backup-protection-readiness.py"
NAMESPACE = "piraeus-datastore"
REMOTE = "rustfs-linstor-backups-v2"
SCHEDULES = {
    f"linstor-standard-shard-{index:02d}": {
        "full": f"10 {3 + index * 4} * * *",
        "incremental": "",
        "keep_local": "1",
        "keep_remote": "7",
        "on_failure": "RETRY",
    }
    for index in range(6)
}


class ReconcileError(RuntimeError):
    pass


def run(args: list[str], timeout: int = 120) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # CLI stderr can include controller details. Keep it out of reports.
        raise ReconcileError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result.stdout


def kubectl_json(*args: str) -> dict[str, Any]:
    try:
        value = json.loads(run(["kubectl", *args, "-o", "json"]))
    except (json.JSONDecodeError, ReconcileError) as exc:
        raise ReconcileError("Kubernetes inventory query failed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ReconcileError("Kubernetes inventory was not a List")
    return value


def linstor(*args: str, machine: bool = False) -> str:
    prefix = ["kubectl", "-n", NAMESPACE, "exec", "deploy/linstor-controller", "--", "linstor"]
    if machine:
        prefix.append("-m")
    return run(prefix + list(args))


def table_rows(output: str) -> list[list[str]]:
    result: list[list[str]] = []
    for line in output.splitlines():
        if "|" not in line:
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if fields and fields[0] and not set(fields[0]) <= {"=", "-", "┄", "╌"}:
            result.append(fields)
    return result


def parse_plan() -> list[dict[str, str]]:
    with PLAN.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ReconcileError("schedule plan is empty")
    return [row for row in rows if row["backup_producer"] == "LINSTOR S3 schedule"]


def live_handle_map() -> dict[str, str]:
    pvc_items = kubectl_json("get", "pvc", "-A")["items"]
    pv_items = kubectl_json("get", "pv")["items"]
    pv_by_name = {(x.get("metadata") or {}).get("name", ""): x for x in pv_items}
    out: dict[str, str] = {}
    for pvc in pvc_items:
        meta = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        if spec.get("storageClassName") != "linstor" or (pvc.get("status") or {}).get("phase") != "Bound":
            continue
        pv = pv_by_name.get(spec.get("volumeName", ""), {})
        csi = (pv.get("spec") or {}).get("csi") or {}
        if csi.get("driver") == "linstor.csi.linbit.com" and csi.get("volumeHandle"):
            out[f"{meta.get('namespace', 'default')}/{meta.get('name', '')}"] = csi["volumeHandle"]
    return out


def linstor_resource_health() -> dict[str, bool]:
    # Parse the controller response in memory. It contains internal DRBD
    # authentication fields; none of the raw payload is written or printed.
    try:
        payload = json.loads(linstor("resource", "list", machine=True))
    except (json.JSONDecodeError, ReconcileError) as exc:
        raise ReconcileError("LINSTOR resource inventory failed") from exc
    found: dict[str, list[dict[str, Any]]] = {}
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "name" in value and "node_name" in value and isinstance(value.get("volumes"), list):
                found.setdefault(str(value["name"]), []).append(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)

    result: dict[str, bool] = {}
    for name, replicas in found.items():
        diskful_up_to_date = 0
        valid = True
        for replica in replicas:
            for volume in replica.get("volumes") or []:
                provider = volume.get("provider_kind")
                state = (volume.get("state") or {}).get("disk_state")
                if provider == "LVM_THIN" and state == "UpToDate":
                    diskful_up_to_date += 1
                elif provider == "DISKLESS" and state == "Diskless":
                    continue
                else:
                    valid = False
        result[name] = valid and diskful_up_to_date >= 2
    return result


def gate(pre_schedule: bool) -> tuple[int, str]:
    args = [sys.executable, str(GATE)]
    if pre_schedule:
        args.append("--pre-schedule")
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return result.returncode, (result.stdout + result.stderr).strip()


def current_schedules() -> dict[str, dict[str, str]]:
    rows = table_rows(linstor("schedule", "list", "--pastable"))
    schedules: dict[str, dict[str, str]] = {}
    for fields in rows:
        if fields[0].lower() == "name" or len(fields) < 6:
            continue
        schedules[fields[0]] = {
            "full": fields[1],
            "incremental": fields[2],
            "keep_local": fields[3],
            "keep_remote": fields[4],
            "on_failure": fields[5],
        }
    return schedules


def active_bindings() -> list[tuple[str, str, str]]:
    rows = table_rows(
        linstor("schedule", "list-by-resource", "--active-only", "--pastable")
    )
    result: list[tuple[str, str, str]] = []
    for fields in rows:
        if len(fields) >= 3 and fields[0].lower() != "resource":
            result.append((fields[0], fields[1], fields[2]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="reconcile planned schedules after all gates pass")
    args = parser.parse_args()
    try:
        plan = parse_plan()
        handles = live_handle_map()
        health = linstor_resource_health()
        unresolved = [
            row for row in plan
            if row.get("consistency_gate")
            and not row["consistency_gate"].startswith("Keep protected")
        ]
        failures: list[str] = []
        for row in plan:
            claim = f"{row['namespace']}/{row['pvc']}"
            handle = handles.get(claim)
            if not handle or handle != row["linstor_resource"]:
                failures.append(f"{claim}: live PVC-to-LINSTOR mapping differs from reviewed plan")
            elif not health.get(handle, False):
                failures.append(f"{claim}: LINSTOR resource is not healthy on thin-provisioned replicas")
        if failures:
            print("BLOCKED: resource plan is stale or resources are unhealthy", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            return 1

        print(f"Planned LINSTOR S3 resources: {len(plan)}")
        for row in plan:
            print(
                f"{row['namespace']}/{row['pvc']}\t{row['linstor_resource']}\t"
                f"{row['schedule_name']}\t{row['daily_full_cron_utc']}"
            )
        if unresolved:
            print(f"Application consistency gates still open: {len(unresolved)}")
            for row in unresolved:
                print(f"  - {row['namespace']}/{row['pvc']}: {row['consistency_gate']}")
        if not args.apply:
            print("PLAN ONLY: no LINSTOR schedules were changed")
            return 0
        if unresolved:
            raise ReconcileError("application consistency gates must be resolved before enabling schedules")

        code, output = gate(pre_schedule=True)
        if code:
            print(output, file=sys.stderr)
            raise ReconcileError("protection prerequisites have not all passed")

        expected_pairs = {
            row["linstor_resource"]: row["schedule_name"] for row in plan
        }
        existing_bindings = active_bindings()
        for resource, remote, schedule_name in existing_bindings:
            if remote != REMOTE:
                raise ReconcileError("an active schedule targets a non-v2 remote")
            if expected_pairs.get(resource) != schedule_name:
                raise ReconcileError("an active schedule differs from the reviewed resource plan")

        current = current_schedules()
        for name, policy in SCHEDULES.items():
            if name in current:
                if current[name] != policy:
                    raise ReconcileError(f"existing LINSTOR schedule {name} has different retention or timing")
                continue
            linstor(
                "schedule", "create", name, policy["full"],
                "--keep-local", policy["keep_local"],
                "--keep-remote", policy["keep_remote"],
                "--on-failure", policy["on_failure"],
                "--max-retries", "10",
            )

        already = {(resource, schedule) for resource, remote, schedule in existing_bindings if remote == REMOTE}
        for row in plan:
            resource, schedule = row["linstor_resource"], row["schedule_name"]
            if (resource, schedule) in already:
                continue
            linstor("backup", "schedule", "enable", "--rd", resource, REMOTE, schedule)

        code, output = gate(pre_schedule=False)
        print(output)
        if code:
            raise ReconcileError("schedules were applied, but the final protection gate did not pass; retain state for review")
        print("PASS: LINSTOR schedules match the approved live workload plan")
        return 0
    except (OSError, subprocess.TimeoutExpired, ReconcileError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
