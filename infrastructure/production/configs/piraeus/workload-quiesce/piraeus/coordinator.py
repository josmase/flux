#!/usr/bin/env python3
"""Quiesce one application, create a LINSTOR snapshot, then upload that snapshot.

The default invocation is a read-only plan. Production CronJobs must pass
--execute explicitly. The script fails closed unless the PVC-to-LINSTOR mapping
and exact PVC-to-LINSTOR mapping match the reviewed plan. Workload state is
restored in a finally path even when LINSTOR does not create a local snapshot
before the deadline.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any


REMOTE = "rustfs-linstor-backups-v2"
CONTROLLER_NS = "piraeus-datastore"
CONTROLLER = "deploy/linstor-controller"
SNAPSHOT_TIMEOUT_SECONDS = 900
REMOTE_BACKUP_TIMEOUT_SECONDS = 1800
REMOTE_RETENTION_COUNT = 7
KUBECTL = os.environ.get("KUBECTL", "/opt/backup-tools/kubectl")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
UTC = dt.timezone.utc


@dataclass(frozen=True)
class Target:
    namespace: str
    pvc: str
    resource: str
    strategy: str


TARGETS = {
    "felis-uploads": Target(
        "felis", "felis-uploads", "pvc-323137aa-9bf0-43bc-96c0-e913bea91641",
        "scale-api",
    ),
    "felis-registry": Target(
        "felis", "registry", "pvc-1c2eb97f-abb1-4f93-82c6-34d465e0e14d",
        "registry-lease",
    ),
    "minecraft-lobby": Target(
        "minecraft", "world-lobby-0", "pvc-702f006e-6a90-4ab8-9f81-ae3f6da58281",
        "rcon-save-freeze",
    ),
    "minecraft-login": Target(
        "minecraft", "world-login-0", "pvc-36d3b8f1-52bb-4b8c-8fc2-13e364e8bb00",
        "stop-server",
    ),
}


class CoordinatorError(RuntimeError):
    pass


def command(args: list[str], *, timeout: int = 60, input_text: str | None = None) -> str:
    result = subprocess.run(
        args, input=input_text, text=True, capture_output=True, timeout=timeout,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CoordinatorError(f"command {args[0]} failed: {detail[:500]}")
    return result.stdout


def kubectl(*args: str, timeout: int = 60, input_text: str | None = None) -> str:
    return command([KUBECTL, *args], timeout=timeout, input_text=input_text)


def kubectl_json(*args: str) -> dict[str, Any]:
    try:
        value = json.loads(kubectl(*args, "-o", "json"))
    except json.JSONDecodeError as exc:
        raise CoordinatorError("Kubernetes returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise CoordinatorError("Kubernetes response was not an object")
    return value


def linstor(*args: str, timeout: int = 120) -> str:
    return kubectl(
        "-n", CONTROLLER_NS, "exec", CONTROLLER, "--", "linstor", *args,
        timeout=timeout,
    )


def table_rows(output: str) -> list[list[str]]:
    rows = []
    for raw in ANSI.sub("", output).splitlines():
        line = raw.strip()
        if not line.startswith("|") or "=" * 3 in line:
            continue
        fields = [item.strip() for item in line.strip("|").split("|")]
        if fields and fields[0].lower() not in {"resource", "resourcename", "name"}:
            rows.append(fields)
    return rows


def verify_live_mapping(target: Target) -> None:
    pvc = kubectl_json("-n", target.namespace, "get", "pvc", target.pvc)
    if pvc.get("status", {}).get("phase") != "Bound":
        raise CoordinatorError("target PVC is not Bound")
    if pvc.get("spec", {}).get("storageClassName") != "linstor":
        raise CoordinatorError("target PVC no longer uses the approved LINSTOR StorageClass")
    pv_name = pvc.get("spec", {}).get("volumeName")
    if not pv_name:
        raise CoordinatorError("target PVC has no bound PV")
    pv = kubectl_json("get", "pv", pv_name)
    csi = pv.get("spec", {}).get("csi", {})
    if csi.get("driver") != "linstor.csi.linbit.com" or csi.get("volumeHandle") != target.resource:
        raise CoordinatorError("live PVC-to-LINSTOR resource mapping differs from the reviewed plan")


def snapshot_rows(target: Target) -> list[dict[str, str]]:
    rows = table_rows(linstor("snapshot", "list", "--pastable", "--no-truncate", "--resources", target.resource))
    result = []
    for row in rows:
        if len(row) < 6 or row[0] != target.resource:
            continue
        result.append({
            "name": row[1], "nodes": row[2], "volumes": row[3],
            "created": row[4], "state": row[5],
        })
    return result


def wait_for_snapshot(target: Target, snapshot_name: str) -> None:
    deadline = time.monotonic() + SNAPSHOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            matching = [row for row in snapshot_rows(target) if row["name"] == snapshot_name]
        except CoordinatorError:
            time.sleep(5)
            continue
        if matching:
            state = matching[0]["state"].strip().lower()
            if state in {"successful", "success", "ok"}:
                return
            if state in {"failed", "error"}:
                raise CoordinatorError("LINSTOR reported a failed local snapshot")
        time.sleep(3)
    raise CoordinatorError("LINSTOR local snapshot did not become successful before timeout")


def wait_for_remote_backup(target: Target, snapshot_name: str) -> str:
    deadline = time.monotonic() + REMOTE_BACKUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            rows = table_rows(linstor(
                "backup", "list", "--pastable", "--no-truncate", "--show-id",
                "-r", target.resource, REMOTE,
            ))
        except CoordinatorError:
            time.sleep(5)
            continue
        matches = [row for row in rows if len(row) >= 6 and row[0] == target.resource and row[1] == snapshot_name]
        for row in matches:
            status = row[4].strip().lower()
            if status == "success" and row[2].strip():
                return row[5]
            if status in {"failed", "error"}:
                raise CoordinatorError("LINSTOR reported a failed remote backup for the scheduled snapshot")
        time.sleep(30)
    raise CoordinatorError("remote LINSTOR backup did not become successful before timeout")


def managed_generation_time(target_name: str, snapshot_name: str) -> dt.datetime | None:
    match = re.fullmatch(
        rf"coord-{re.escape(target_name)}-(\d{{8}}t\d{{6}})", snapshot_name,
    )
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(1), "%Y%m%dt%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def prune_managed_generations(target_name: str, target: Target) -> None:
    """Keep seven successful managed full backups; never select other IDs."""
    rows = table_rows(linstor(
        "backup", "list", "--pastable", "--no-truncate", "--show-id",
        "-r", target.resource, REMOTE,
    ))
    managed = []
    for row in rows:
        if len(row) < 6:
            continue
        created = managed_generation_time(target_name, row[1])
        if created is None:
            continue
        if row[0] != target.resource or row[4].strip().lower() != "success" or row[3].strip():
            raise CoordinatorError("managed backup set contains a non-successful or incremental record; retention stops")
        backup_id = row[5].strip()
        if not backup_id.startswith(f"{target.resource}_"):
            raise CoordinatorError("managed backup ID does not match the target LINSTOR resource")
        managed.append((created, row[1], backup_id))
    managed.sort(key=lambda entry: entry[0], reverse=True)
    if len(managed) <= REMOTE_RETENTION_COUNT:
        print(f"managed remote generations={len(managed)}; no retention deletion required")
        return
    expired = managed[REMOTE_RETENTION_COUNT:]
    snapshots = {row["name"] for row in snapshot_rows(target)}
    for _created, snapshot_name, backup_id in expired:
        # LINSTOR's dry-run is required immediately before the exact-ID removal.
        linstor("backup", "delete", "id", REMOTE, backup_id, "--dry-run", "--keep-snaps")
        linstor("backup", "delete", "id", REMOTE, backup_id, "--keep-snaps")
        remaining = table_rows(linstor(
            "backup", "list", "--pastable", "--no-truncate", "--show-id",
            "-r", target.resource, REMOTE,
        ))
        if any(len(row) >= 2 and row[0] == target.resource and row[1] == snapshot_name for row in remaining):
            raise CoordinatorError("expired remote generation remains after exact-ID deletion")
        if snapshot_name in snapshots:
            linstor("snapshot", "delete", target.resource, snapshot_name)
            if snapshot_name in {row["name"] for row in snapshot_rows(target)}:
                raise CoordinatorError("expired local snapshot remains after deletion")
        print(f"expired managed full generation removed: {snapshot_name}")


def wait_pvc_detached(target: Target, *, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pods = kubectl_json("-n", target.namespace, "get", "pods").get("items", [])
        users = []
        for pod in pods:
            for volume in pod.get("spec", {}).get("volumes", []):
                if volume.get("persistentVolumeClaim", {}).get("claimName") == target.pvc:
                    users.append(pod.get("metadata", {}).get("name", "unknown"))
                    break
        if not users:
            return
        time.sleep(2)
    raise CoordinatorError("PVC still has pod consumers after quiescence timeout")


def begin_scale_api(target: Target) -> dict[str, Any]:
    deployment = kubectl_json("-n", target.namespace, "get", "deployment", "felis-api")
    replicas = int(deployment.get("spec", {}).get("replicas", 0))
    if replicas < 1:
        raise CoordinatorError("Felis API has no ready desired replica to preserve")
    state = {"replicas": replicas}
    try:
        kubectl("-n", target.namespace, "scale", "deployment/felis-api", "--replicas=0")
        wait_pvc_detached(target)
    except Exception:
        try:
            end_scale_api(target, state)
        except Exception as restore_error:
            raise CoordinatorError(f"CRITICAL: Felis API quiesce failed and restore failed: {restore_error}")
        raise
    return state


def end_scale_api(target: Target, state: dict[str, Any]) -> None:
    kubectl(
        "-n", target.namespace, "scale", "deployment/felis-api",
        f"--replicas={state['replicas']}",
    )
    kubectl("-n", target.namespace, "rollout", "status", "deployment/felis-api", "--timeout=300s", timeout=320)


def registry_request(target: Target, endpoint: str) -> None:
    kubectl(
        "-n", target.namespace, "exec", "deployment/registry", "-c", "registry-gc", "--",
        "wget", "-q", "-O", "/dev/null", "--post-data", "", f"http://127.0.0.1:5002/{endpoint}",
    )


def begin_registry(target: Target) -> dict[str, Any]:
    registry_request(target, "readonly?lease=1800")
    return {"locked": True}


def end_registry(target: Target, state: dict[str, Any]) -> None:
    if state.get("locked"):
        registry_request(target, "readwrite")


def rcon_packet(sock: socket.socket, request_id: int, packet_type: int, payload: str) -> None:
    body = struct.pack("<ii", request_id, packet_type) + payload.encode() + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(body)) + body)


def rcon_response(sock: socket.socket) -> tuple[int, str]:
    def receive(count: int) -> bytes:
        result = b""
        while len(result) < count:
            part = sock.recv(count - len(result))
            if not part:
                raise CoordinatorError("RCON connection closed before a response")
            result += part
        return result
    length = struct.unpack("<i", receive(4))[0]
    body = receive(length)
    request_id, _ = struct.unpack("<ii", body[:8])
    return request_id, body[8:-2].decode("utf-8", "replace")


def rcon_command(sock: socket.socket, request_id: int, payload: str) -> str:
    rcon_packet(sock, request_id, 2, payload)
    while True:
        response_id, response = rcon_response(sock)
        if response_id == request_id:
            return response


def rcon_once(ip: str, password: str, command_text: str) -> str:
    sock = socket.create_connection((ip, 25575), timeout=10)
    sock.settimeout(10)
    try:
        rcon_packet(sock, 1, 3, password)
        response_id, _ = rcon_response(sock)
        if response_id != 1:
            raise CoordinatorError("RCON authentication failed")
        return rcon_command(sock, 2, command_text)
    finally:
        sock.close()


def begin_lobby(target: Target) -> dict[str, Any]:
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        raise CoordinatorError("RCON_PASSWORD is not supplied by the existing Secret reference")
    pod = kubectl_json("-n", target.namespace, "get", "pod", "lobby-0")
    ip = pod.get("status", {}).get("podIP")
    if not ip:
        raise CoordinatorError("Lobby Pod has no IP")
    disabled = rcon_once(ip, password, "save-off")
    if "disabled" not in disabled.lower():
        try:
            rcon_once(ip, password, "save-on")
        except Exception as restore_error:
            raise CoordinatorError(f"CRITICAL: Lobby save-off response was unexpected and save-on failed: {restore_error}")
        raise CoordinatorError("Lobby did not confirm save-off")
    try:
        rcon_once(ip, password, "save-all flush")
    except Exception:
        try:
            rcon_once(ip, password, "save-on")
        except Exception as restore_error:
            raise CoordinatorError(f"CRITICAL: Lobby flush failed and save-on could not be confirmed: {restore_error}")
        raise
    return {"pod_ip": ip, "password": password, "saving_disabled": True}


def end_lobby(target: Target, state: dict[str, Any]) -> None:
    if not state.get("saving_disabled"):
        return
    enabled = rcon_once(state["pod_ip"], state["password"], "save-on")
    if "enabled" not in enabled.lower():
        raise CoordinatorError("Lobby did not confirm save-on")


def begin_login(target: Target) -> dict[str, Any]:
    server = kubectl_json("-n", target.namespace, "get", "minecraftserver", "login")
    desired_state = (server.get("spec") or {}).get("desiredState")
    if desired_state != "Running":
        raise CoordinatorError("Login is not desired Running; refusing to change its maintenance state")
    state = {"stopped": True, "desired_state": desired_state}
    try:
        kubectl(
            "-n", target.namespace, "patch", "minecraftserver", "login",
            "--type=merge", "-p", '{"spec":{"desiredState":"Stopped"}}',
        )
        wait_pvc_detached(target, timeout=300)
    except Exception:
        end_login(target, state)
        raise
    return state


def end_login(target: Target, state: dict[str, Any]) -> None:
    if not state.get("stopped"):
        return
    kubectl(
        "-n", target.namespace, "patch", "minecraftserver", "login",
            "--type=merge", "-p", json.dumps({"spec": {"desiredState": state["desired_state"]}}),
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        pod = subprocess.run(
            [KUBECTL, "-n", target.namespace, "get", "pod", "login-0", "-o", "json"],
            text=True, capture_output=True, timeout=30,
        )
        if pod.returncode == 0:
            obj = json.loads(pod.stdout)
            statuses = obj.get("status", {}).get("containerStatuses", [])
            if obj.get("status", {}).get("phase") == "Running" and statuses and all(c.get("ready") for c in statuses):
                return
        time.sleep(3)
    raise CoordinatorError("Login did not return Ready within the restore timeout")


STRATEGIES = {
    "scale-api": (begin_scale_api, end_scale_api),
    "registry-lease": (begin_registry, end_registry),
    "rcon-save-freeze": (begin_lobby, end_lobby),
    "stop-server": (begin_login, end_login),
}


def run(target_name: str, execute: bool, prune_retention: bool) -> int:
    target = TARGETS[target_name]
    verify_live_mapping(target)
    now = dt.datetime.now(UTC)
    snapshot_name = f"coord-{target_name}-{now.strftime('%Y%m%dt%H%M%S')}"
    print(f"target={target_name} resource={target.resource} snapshot={snapshot_name} strategy={target.strategy}")
    if not execute:
        print("PLAN ONLY: no workload state changed")
        return 0
    if snapshot_name in {row["name"] for row in snapshot_rows(target)}:
        raise CoordinatorError("generated snapshot name already exists; refusing to overwrite or reuse it")
    begin, end = STRATEGIES[target.strategy]
    state: dict[str, Any] | None = None
    operation_error: Exception | None = None
    source_snapshot: str | None = None
    try:
        state = begin(target)
        linstor(
            "snapshot", "create", target.resource, snapshot_name,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
        wait_for_snapshot(target, snapshot_name)
        print(f"LINSTOR local snapshot completed while quiesced: {snapshot_name}")
        source_snapshot = snapshot_name
    except Exception as exc:
        operation_error = exc
    finally:
        if state is not None:
            try:
                end(target, state)
                print("target workload state restored")
            except Exception as exc:
                raise CoordinatorError(f"CRITICAL: workload restoration failed: {exc}") from exc
    if operation_error:
        raise operation_error
    if source_snapshot is None:
        raise CoordinatorError("quiescence completed without identifying the source snapshot")
    linstor(
        "backup", "create", "--full", "--source-snapshot", source_snapshot,
        REMOTE, target.resource, timeout=REMOTE_BACKUP_TIMEOUT_SECONDS,
    )
    backup_id = wait_for_remote_backup(target, source_snapshot)
    print(f"LINSTOR remote backup completed successfully: {backup_id}")
    if prune_retention:
        prune_managed_generations(target_name, target)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--execute", action="store_true", help="quiesce, create a snapshot, restore, and upload that snapshot")
    parser.add_argument("--prune-retention", action="store_true", help="retain seven successful managed full backups and prune only older exact IDs")
    args = parser.parse_args()
    try:
        if args.prune_retention and not args.execute:
            raise CoordinatorError("retention pruning requires --execute")
        return run(args.target, args.execute, args.prune_retention)
    except (CoordinatorError, OSError, subprocess.TimeoutExpired, KeyError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
