#!/usr/bin/env python3
"""Fail a read-only check when active LINSTOR schedules lack fresh v2 backups."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys


NAMESPACE = "piraeus-datastore"
CONTROLLER = "deploy/linstor-controller"
REMOTE = os.environ.get("LINSTOR_BACKUP_REMOTE", "rustfs-linstor-backups-v2")
MAX_AGE_SECONDS = int(os.environ.get("MAX_BACKUP_AGE_SECONDS", "90000"))
KUBECTL = os.environ.get("KUBECTL", "kubectl")


class CheckError(RuntimeError):
    pass


def command(args: list[str], timeout: int = 120) -> str:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckError(f"command failed ({args[0]}): {detail[:500]}")
    return result.stdout


def linstor_json(*args: str) -> dict:
    output = command([
        KUBECTL, "-n", NAMESPACE, "exec", CONTROLLER, "--", "linstor", "-m", *args,
    ])
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CheckError("LINSTOR returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise CheckError("LINSTOR returned an unexpected JSON value")
    if any(isinstance(item, dict) and item.get("ret_code", 0) < 0 for item in value.get("data", [])):
        raise CheckError("LINSTOR returned an API error in the active schedule inventory")
    return value


def main() -> int:
    schedules = linstor_json("schedule", "list-by-resource", "--active-only").get("data")
    if not isinstance(schedules, list) or not schedules:
        raise CheckError("no active LINSTOR resource schedules were returned")

    unexpected = [
        (schedule.get("rsc_name"), schedule.get("remote_name"))
        for schedule in schedules
        if not schedule.get("rsc_name") or schedule.get("remote_name") != REMOTE
    ]
    if unexpected:
        for resource, remote in unexpected:
            print(
                f"MISMATCH active resource {resource or '<missing>'} targets "
                f"unexpected remote {remote!r}; expected {REMOTE!r}",
                file=sys.stderr,
                flush=True,
            )
        return 1

    catalog = linstor_json("backup", "list", REMOTE)
    records = catalog.get("linstor")
    if not isinstance(records, dict):
        raise CheckError(f"remote {REMOTE} returned no LINSTOR backup catalog")

    now = dt.datetime.now(dt.timezone.utc).timestamp()
    failures: list[str] = []
    for schedule in schedules:
        resource = schedule.get("rsc_name")
        remote = schedule.get("remote_name")
        matches = [record for record in records.values() if record.get("origin_rsc") == resource]
        if not matches:
            failures.append(f"{resource}: no remote backup record exists in {REMOTE}")
            continue

        latest = max(matches, key=lambda record: int(record.get("finished_timestamp") or 0))
        backup_id = latest.get("id", "<missing-id>")
        finished_ms = int(latest.get("finished_timestamp") or 0)
        if latest.get("success") is not True or latest.get("restorable") is not True or latest.get("shipping"):
            failures.append(f"{resource}: latest remote record {backup_id} is not successful and restorable")
            continue
        if latest.get("origin_rsc") != resource:
            failures.append(f"{resource}: latest remote record {backup_id} has a mismatched source resource")
            continue
        age_seconds = now - finished_ms / 1000
        if finished_ms <= 0 or age_seconds < -120 or age_seconds > MAX_AGE_SECONDS:
            failures.append(
                f"{resource}: latest remote record {backup_id} age is {int(age_seconds)}s; "
                f"maximum is {MAX_AGE_SECONDS}s"
            )
            continue
        print(
            f"PASS resource={resource} remote={REMOTE} backup_id={backup_id} "
            f"age_seconds={int(age_seconds)} restorable=true",
            flush=True,
        )

    if failures:
        for failure in failures:
            print("MISMATCH " + failure, file=sys.stderr, flush=True)
        return 1
    print(f"PASS checked {len(schedules)} active LINSTOR resource schedule(s)", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CheckError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"LINSTOR remote backup check failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
