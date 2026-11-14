#!/usr/bin/env python3
"""Plan or safely reconcile the approved LINSTOR-to-RustFS schedules.

The default mode is read-only. `--pilot --apply` enables only the reviewed T5.4
pilot resource after the protection gate and that resource's baseline and
consistency checks pass. Broad `--apply` additionally requires recorded pilot
acceptance and every application-consistency gate to pass. It enables schedules
only on explicitly listed resource definitions; it never enables a
controller-wide or resource-group schedule.
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
PILOT_EVIDENCE = ROOT / "docs/LINSTOR_T5_4_PILOT_EVIDENCE_2026-11-14.json"
NAMESPACE = "piraeus-datastore"
REMOTE = "rustfs-linstor-backups-v2"
PILOT_CLAIM = "media/arr-dashboard-config-linstor"
SCHEDULES = {
    f"linstor-standard-shard-{index:02d}": {
        "full": f"10 {3 + index * 4} * * *",
        "incremental": "",
        "keep_local": "1",
        "keep_remote": "7",
        "on_failure": "RETRY(10)",
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


def gate(pre_schedule: bool, pilot_resource: str | None = None) -> tuple[int, str]:
    args = [sys.executable, str(GATE)]
    if pre_schedule:
        args.append("--pre-schedule")
    if pilot_resource:
        args.extend(["--pilot-resource", pilot_resource])
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return result.returncode, (result.stdout + result.stderr).strip()


def require_pilot_acceptance(plan: list[dict[str, str]]) -> None:
    try:
        evidence = json.loads(PILOT_EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError("T5.4 pilot evidence is missing or invalid; broad rollout is blocked") from exc
    row = next((item for item in plan if f"{item['namespace']}/{item['pvc']}" == PILOT_CLAIM), None)
    if not row:
        raise ReconcileError("approved T5.4 pilot claim is missing from the current plan")
    required = {
        "status": "PASS",
        "claim": PILOT_CLAIM,
        "baseline_snapshot": "t34-20261113-arr-dashboard-config-linstor-d60112",
        "schedule_name": row["schedule_name"],
        "remote_backup_restorable": True,
        "restore_sha256_match": True,
        "resource_health_unchanged": True,
    }
    if any(evidence.get(key) != value for key, value in required.items()):
        raise ReconcileError("T5.4 pilot evidence does not prove a successful restorable LINSTOR pilot")
    interval = evidence.get("observed_interval_hours")
    if not isinstance(interval, (int, float)) or interval < 24:
        raise ReconcileError("T5.4 pilot evidence does not cover a full standard RPO interval")
    if not evidence.get("completed_at_utc") or not evidence.get("backup_id"):
        raise ReconcileError("T5.4 pilot evidence is missing its completion time or successful backup ID")


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
    parser.add_argument(
        "--pilot",
        action="store_true",
        help=f"enable only the reviewed T5.4 pilot resource ({PILOT_CLAIM}); broad rollout requires recorded pilot acceptance",
    )
    args = parser.parse_args()
    try:
        plan = parse_plan()
        selected = [
            row for row in plan
            if not args.pilot or f"{row['namespace']}/{row['pvc']}" == PILOT_CLAIM
        ]
        if args.pilot and len(selected) != 1:
            raise ReconcileError("the approved T5.4 pilot claim is missing or duplicated in the plan")
        handles = live_handle_map()
        health = linstor_resource_health()
        unresolved = [
            row for row in selected
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

        print(f"Planned LINSTOR S3 resources in this scope: {len(selected)} (full plan: {len(plan)})")
        for row in selected:
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
        if args.pilot:
            pilot = selected[0]
            if pilot.get("s3_v2_baseline") != "Ready":
                raise ReconcileError("T5.4 pilot claim has no Ready RustFS v2 baseline")
            if pilot.get("consistency_gate"):
                raise ReconcileError("T5.4 pilot claim still has an application-consistency gate")
        else:
            if unresolved:
                raise ReconcileError("application consistency gates must be resolved before broad rollout")
            require_pilot_acceptance(plan)

        pilot_resource = selected[0]["linstor_resource"] if args.pilot else None
        code, output = gate(pre_schedule=True, pilot_resource=pilot_resource)
        if code:
            print(output, file=sys.stderr)
            raise ReconcileError("protection prerequisites have not all passed")

        expected_pairs = {row["linstor_resource"]: row["schedule_name"] for row in selected}
        existing_bindings = active_bindings()
        for resource, remote, schedule_name in existing_bindings:
            if remote != REMOTE:
                raise ReconcileError("an active schedule targets a non-v2 remote")
            if expected_pairs.get(resource) != schedule_name:
                raise ReconcileError("an active schedule differs from the reviewed resource plan")
        if args.pilot and any(resource not in expected_pairs for resource, _, _ in existing_bindings):
            raise ReconcileError("an active schedule exists outside the selected pilot scope")

        current = current_schedules()
        selected_schedule_names = (
            {row["schedule_name"] for row in selected} if args.pilot else set(SCHEDULES)
        )
        for name in sorted(selected_schedule_names):
            policy = SCHEDULES[name]
            if name in current:
                if current[name] != policy:
                    raise ReconcileError(f"existing LINSTOR schedule {name} has different retention or timing")
                continue
            linstor(
                "schedule", "create", name, policy["full"],
                "--keep-local", policy["keep_local"],
                "--keep-remote", policy["keep_remote"],
                "--on-failure", policy["on_failure"].split("(", 1)[0],
                "--max-retries", policy["on_failure"].split("(", 1)[1].rstrip(")"),
            )

        already = {(resource, schedule) for resource, remote, schedule in existing_bindings if remote == REMOTE}
        for row in selected:
            resource, schedule = row["linstor_resource"], row["schedule_name"]
            if (resource, schedule) in already:
                continue
            linstor("backup", "schedule", "enable", "--rd", resource, REMOTE, schedule)

        if args.pilot:
            code, output = gate(pre_schedule=False, pilot_resource=selected[0]["linstor_resource"])
        else:
            code, output = gate(pre_schedule=False)
        print(output)
        if code:
            raise ReconcileError("schedules were applied, but the final protection gate did not pass; retain state for review")
        if args.pilot:
            print("PILOT ENABLED: only the reviewed T5.4 resource is scheduled; collect a full-interval backup and restore before broad rollout")
        else:
            print("PASS: LINSTOR schedules match the approved live workload plan")
        return 0
    except (OSError, subprocess.TimeoutExpired, ReconcileError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
