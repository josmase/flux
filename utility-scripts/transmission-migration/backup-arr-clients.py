#!/usr/bin/env python3
"""
backup-arr-clients.py — Create manual backups and capture pre-change state for all arr instances.
"""

import json
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

CTX = ssl._create_unverified_context()
BACKUP_DIR = Path(".tmp/transmission-in-cluster/arr-backups")

RADARR_INSTANCES = [f"radarr-{i}" for i in range(1, 13)]
SONARR_INSTANCES = [f"sonarr-{i}" for i in range(1, 7)]
ALL_INSTANCES = RADARR_INSTANCES + SONARR_INSTANCES


def fetch_api_key(deployment: str) -> str:
    raw = subprocess.check_output(
        ["kubectl", "exec", "-n", "media", f"deploy/{deployment}", "--", "cat", "/config/config.xml"],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", raw)
    if not match:
        raise RuntimeError(f"API key not found in {deployment}")
    return match.group(1)


def api_request(instance: str, api_key: str, method: str, path: str, body=None):
    url = f"https://{instance}.local.hejsan.xyz/api/v3{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Api-Key", api_key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {error_body}")
    except Exception as e:
        raise RuntimeError(f"{method} {path}: {e}")


def get_schema(instance: str, api_key: str):
    return api_request(instance, api_key, "GET", "/downloadclient/schema")


def get_clients(instance: str, api_key: str):
    return api_request(instance, api_key, "GET", "/downloadclient")


def get_mappings(instance: str, api_key: str):
    return api_request(instance, api_key, "GET", "/remotepathmapping")


def trigger_backup(instance: str, api_key: str):
    return api_request(instance, api_key, "POST", "/command", {"name": "Backup"})


def list_backups(instance: str, api_key: str):
    return api_request(instance, api_key, "GET", "/system/backup")


def redact_client(client: dict) -> dict:
    """Redact sensitive fields from a client record."""
    redacted = {
        "id": client.get("id"),
        "name": client.get("name"),
        "enable": client.get("enable"),
        "implementation": client.get("implementation"),
        "configContract": client.get("configContract"),
    }
    safe_fields = []
    sensitive_names = {"password", "apiKey", "api_key", "secret", "token"}
    for field in client.get("fields", []):
        name = field.get("name", "")
        if name in sensitive_names:
            safe_fields.append({"name": name, "value": "***REDACTED***" if field.get("value") else ""})
        else:
            safe_fields.append(field)
    redacted["fields"] = safe_fields
    return redacted


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_index = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instances": {},
    }
    redacted_state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instances": {},
    }

    for instance in ALL_INSTANCES:
        is_radarr = instance.startswith("radarr-")
        deployment = f"{instance}-{instance.split('-')[0]}"
        print(f"Processing {instance}...")

        api_key = fetch_api_key(deployment)

        # Get pre-change state (redacted)
        clients = get_clients(instance, api_key)
        mappings = get_mappings(instance, api_key)
        redacted_state["instances"][instance] = {
            "clients": [redact_client(c) for c in clients],
            "remote_path_mappings": mappings,
        }

        # Trigger manual backup
        backup_result = trigger_backup(instance, api_key)
        # Get latest backup info
        backups = list_backups(instance, api_key)
        latest = max(backups, key=lambda b: b.get("time", "")) if backups else None
        backup_index["instances"][instance] = {
            "deployment": deployment,
            "backup_trigger": str(backup_result),
            "latest_backup": {
                "id": latest.get("id") if latest else None,
                "time": latest.get("time") if latest else None,
                "name": latest.get("name") if latest else None,
                "type": latest.get("type") if latest else None,
            } if latest else None,
        }
        print(f"  Backup triggered: {backup_index['instances'][instance]['latest_backup']}")

    # Write outputs
    with open(BACKUP_DIR / "backup-index.json", "w") as f:
        json.dump(backup_index, f, indent=2)
    with open(BACKUP_DIR / "redacted-client-state.json", "w") as f:
        json.dump(redacted_state, f, indent=2)
    print(f"\nWrote backup-index.json and redacted-client-state.json")
    print(f"Total instances: {len(backup_index['instances'])}")


if __name__ == "__main__":
    main()