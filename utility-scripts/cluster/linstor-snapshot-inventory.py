#!/usr/bin/env python3
"""Read-only LINSTOR snapshot inventory. Run where kubectl can reach production.

The CSV is a review aid, never an instruction to delete anything. Collection
uses bounded kubectl calls and keeps the complete source objects for audit.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


TIMEOUT = 30
PAGE_SIZE = 500


def run(args, destination, optional=False):
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=TIMEOUT)
        destination.write_text(result.stdout)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        if optional:
            destination.with_suffix(".error.txt").write_text(str(error) + "\n")
            return None
        raise RuntimeError(f"Unable to collect {destination.name}: {error}") from error


def collect(output, full_crds, workers):
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    resources = {
        "nodes": ["kubectl", "get", "nodes", "-o", "json"],
        "satellites": ["kubectl", "get", "linstorsatellites.piraeus.io", "-o", "json"],
        "snapshots": ["kubectl", "get", "volumesnapshots", "-A", "-o", "json"],
        "contents": ["kubectl", "get", "volumesnapshotcontents", "-o", "json"],
        "pvcs": ["kubectl", "get", "pvc", "-A", "-o", "json"],
        "pvs": ["kubectl", "get", "pv", "-o", "json"],
        "crds": ["kubectl", "get", "crd", "-o", "json"],
    }
    for name, command in resources.items():
        run(command + ["--request-timeout=25s"], output / f"{name}.json")
    run(["kubectl", "-n", "piraeus-datastore", "exec", "deploy/linstor-controller", "--",
         "linstor", "-m", "snapshot", "list"], output / "linstor-snapshots.json", optional=True)
    backups = run(["kubectl", "-n", "piraeus-datastore", "exec", "deploy/linstor-controller", "--",
                   "linstor", "-m", "backup", "list", "rustfs-linstor-backups"],
                  output / "linstor-backups.json", optional=True)
    if isinstance(backups, list) and any(isinstance(x, dict) and x.get("ret_code", 0) < 0 for x in backups):
        (output / "linstor-backups.error.txt").write_text(
            "LINSTOR reported an error; inspect linstor-backups.json. Backup inventory is unavailable.\n")
    for worker in workers:
        run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", worker,
             "sudo", "-n", "lvs", "--reportformat", "json", "-o",
             "lv_name,vg_name,lv_attr,origin,lv_size,segtype"],
            output / f"lvs-{worker}.json", optional=True)
        run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", worker,
             "sudo", "-n", "vgs", "--reportformat", "json", "-o",
             "vg_name,vg_size,vg_free,vg_mda_count,vg_mda_free"],
            output / f"vgs-{worker}.json", optional=True)
    if full_crds:
        collect_crd_sizes(output)


def collect_crd_sizes(output):
    crds = json.loads((output / "crds.json").read_text())["items"]
    summary = []
    for crd in crds:
        spec = crd["spec"]
        if spec["group"] != "internal.linstor.linbit.com":
            continue
        version = next((v["name"] for v in spec["versions"] if v.get("storage")), None)
        if not version:
            raise RuntimeError(f"No storage version for {crd['metadata']['name']}")
        resource = spec["names"]["plural"]
        base = f"/apis/{spec['group']}/{version}/{resource}"
        count = payload_bytes = 0
        cursor = ""
        while True:
            url = f"{base}?limit={PAGE_SIZE}"
            if cursor:
                url += "&continue=" + quote(cursor, safe="")
            page = run(["kubectl", "get", "--raw", url], output / ".crd-page.json")
            for obj in page["items"]:
                count += 1
                payload_bytes += len(json.dumps(obj, separators=(",", ":")).encode())
            cursor = page.get("metadata", {}).get("continue", "")
            if not cursor:
                break
        summary.append({"resource": resource, "count": count, "json_bytes": payload_bytes})
    (output / "linstor-crd-sizes.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / ".crd-page.json").unlink(missing_ok=True)


def items(output, name):
    return json.loads((output / f"{name}.json").read_text())["items"]


def linstor_snapshots(output):
    path = output / "linstor-snapshots.json"
    if not path.exists():
        return set()
    result = set()
    def walk(value):
        if isinstance(value, dict):
            resource = value.get("resource_name")
            snap = value.get("snapshot_name") or value.get("name")
            if resource and snap:
                result.add((resource, snap))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(json.loads(path.read_text()))
    return result


def analyze(output, ledger=None):
    snapshots = items(output, "snapshots")
    contents = items(output, "contents")
    pvcs = items(output, "pvcs")
    pvs = items(output, "pvs")
    snap_by_key = {(x["metadata"]["namespace"], x["metadata"]["name"]): x for x in snapshots}
    content_by_name = {x["metadata"]["name"]: x for x in contents}
    pvc_by_key = {(x["metadata"]["namespace"], x["metadata"]["name"]): x for x in pvcs}
    pv_by_name = {x["metadata"]["name"]: x for x in pvs}
    backend = linstor_snapshots(output)
    ledger_text = ledger.read_text() if ledger else ""
    restore_refs = set()
    for pvc in pvcs:
        for field in ("dataSource", "dataSourceRef"):
            source = pvc.get("spec", {}).get(field) or {}
            if source.get("kind") == "VolumeSnapshot":
                restore_refs.add((pvc["metadata"]["namespace"], source.get("name")))
    rows = []
    for snapshot in snapshots:
        meta, spec, status = snapshot["metadata"], snapshot["spec"], snapshot.get("status", {})
        namespace, name = meta["namespace"], meta["name"]
        content_name = status.get("boundVolumeSnapshotContentName", "")
        content = content_by_name.get(content_name, {})
        handle = content.get("status", {}).get("snapshotHandle", "")
        parts = handle.removeprefix("InCluster:///").split("/") if handle.startswith("InCluster:///") else []
        backend_match = len(parts) == 2 and tuple(parts) in backend
        pvc_name = spec.get("source", {}).get("persistentVolumeClaimName", "")
        pvc = pvc_by_key.get((namespace, pvc_name), {})
        pv = pv_by_name.get(pvc.get("spec", {}).get("volumeName", ""), {})
        labels = meta.get("labels", {})
        restore_ref = (namespace, name) in restore_refs
        ledger_ref = bool(ledger_text and re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", ledger_text))
        managed = labels.get("protection.josmase.dev/managed", "")
        rows.append({
            "kind": "VolumeSnapshot", "namespace": namespace, "name": name,
            "class": spec.get("volumeSnapshotClassName", ""),
            "policy": content.get("spec", {}).get("deletionPolicy", ""),
            "created": meta.get("creationTimestamp", ""),
            "ready": status.get("readyToUse", ""), "managed": managed,
            "tier": labels.get("protection.josmase.dev/tier", ""),
            "retention": labels.get("protection.josmase.dev/retention", ""),
            "source": labels.get("protection.josmase.dev/source", ""),
            "pvc": pvc_name, "pv": pvc.get("spec", {}).get("volumeName", ""),
            "volume_handle": pv.get("spec", {}).get("csi", {}).get("volumeHandle", ""),
            "content": content_name, "snapshot_handle": handle,
            "backend_match": backend_match, "restore_reference": restore_ref,
            "ledger_reference": ledger_ref if ledger else "unknown",
            "disposition": "hold", "reason": "Within retention, referenced, manual, or unverified recovery value",
        })
    retention_limits = {"hourly": 12, "daily": 7, "weekly": 4}
    groups = {}
    for row in rows:
        if row["managed"] == "true" and row["retention"] in retention_limits:
            key = (row["namespace"], row["tier"], row["source"], row["retention"])
            groups.setdefault(key, []).append(row)
    for key, group in groups.items():
        group.sort(key=lambda row: row["created"], reverse=True)
        for row in group[retention_limits[key[3]]:]:
            if not row["restore_reference"] and row["ledger_reference"] is False:
                row["disposition"] = "review_candidate"
                row["reason"] = "Outside retention; verify backend ownership and restorable backup"
    for content in contents:
        spec, meta = content["spec"], content["metadata"]
        ref = spec.get("volumeSnapshotRef", {})
        if (ref.get("namespace", ""), ref.get("name", "")) in snap_by_key:
            continue
        handle = content.get("status", {}).get("snapshotHandle", "")
        parts = handle.removeprefix("InCluster:///").split("/") if handle.startswith("InCluster:///") else []
        rows.append({
            "kind": "orphan VolumeSnapshotContent", "namespace": ref.get("namespace", ""),
            "name": ref.get("name", ""), "class": spec.get("volumeSnapshotClassName", ""),
            "policy": spec.get("deletionPolicy", ""), "created": meta.get("creationTimestamp", ""),
            "ready": content.get("status", {}).get("readyToUse", ""), "managed": "",
            "tier": "", "retention": "", "source": "", "pvc": "", "pv": "",
            "volume_handle": spec.get("source", {}).get("volumeHandle", ""),
            "content": meta["name"], "snapshot_handle": handle,
            "backend_match": len(parts) == 2 and tuple(parts) in backend,
            "restore_reference": False, "ledger_reference": "unknown",
            "disposition": "review_candidate", "reason": "Parent absent; Retain may be intentional; verify lineage and restore value",
        })
    columns = list(rows[0]) if rows else ["kind", "namespace", "name", "disposition", "reason"]
    with (output / "snapshot-review.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    counts = {"VolumeSnapshot": len(snapshots), "VolumeSnapshotContent": len(contents),
              "orphan_content": sum(x["kind"].startswith("orphan") for x in rows),
              "matched_linstor_snapshots": sum(x["backend_match"] for x in rows),
              "review_candidates": sum(x["disposition"] == "review_candidate" for x in rows),
              "backend_inventory_available": (output / "linstor-snapshots.json").exists(),
              "backup_inventory_available": (output / "linstor-backups.json").exists() and
                                          not (output / "linstor-backups.error.txt").exists(),
              "lv_hosts": sorted(p.stem.removeprefix("lvs-") for p in output.glob("lvs-*.json"))}
    (output / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--collect", action="store_true", help="collect read-only data using kubectl")
    parser.add_argument("--full-crds", action="store_true", help="page through LINSTOR CRDs to count objects and bytes")
    parser.add_argument("--worker", action="append", default=[], help="SSH host for read-only LVM metadata")
    parser.add_argument("--ledger", type=Path, help="migration ledger to mark named rollback artifacts")
    args = parser.parse_args()
    if args.collect:
        collect(args.output_dir, args.full_crds, args.worker)
    analyze(args.output_dir, args.ledger)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, KeyError, ValueError) as error:
        sys.exit(str(error))
