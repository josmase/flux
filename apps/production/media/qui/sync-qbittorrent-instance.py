#!/usr/bin/env python3
"""Keep Qui's saved qBittorrent connection aligned with the managed service."""

import json
import os
import time
import urllib.error
import urllib.request


def request(url, key, method="GET", payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("X-API-Key", key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as response:
        data = response.read()
        return json.loads(data) if data else None


def sync_instances(qui, key, username, password, desired_instances, instances):
    if not isinstance(desired_instances, list) or not desired_instances:
        raise SystemExit("QBITTORRENT_INSTANCES must be a non-empty JSON array")
    if not isinstance(instances, list):
        raise SystemExit("Qui returned an unexpected instance list")

    for desired in desired_instances:
        desired_name = desired.get("name")
        desired_host = desired.get("host")
        if not desired_name or not desired_host:
            raise SystemExit("Each QBITTORRENT_INSTANCES entry needs name and host")
        match = next((item for item in instances if item.get("name") == desired_name), None)
        if match is None:
            request(
                f"{qui}/api/instances",
                key,
                method="POST",
                payload={
                    "name": desired_name,
                    "host": desired_host,
                    "username": username,
                    "password": password,
                },
            )
            print(f"Created Qui instance {desired_name}")
            continue
        instance_id = match.get("id")
        if instance_id is None:
            raise SystemExit(f"Qui instance {desired_name!r} has no id")
        update = {k: v for k, v in match.items() if k not in ("id", "password")}
        update.update(
            {"name": desired_name, "host": desired_host, "username": username, "password": password}
        )
        request(f"{qui}/api/instances/{instance_id}", key, method="PUT", payload=update)
        print(f"Updated Qui instance {desired_name} ({instance_id})")


def main():
    qui = os.environ.get("QUI_URL", "http://qui:7476").rstrip("/")
    key = open("/run/qui-api-key/key", encoding="utf-8").read().strip()
    if not key:
        print("Qui management API key is not configured; skipping sync")
        return
    username = open("/run/qbittorrent-auth/username", encoding="utf-8").read().strip()
    password = open("/run/qbittorrent-auth/password", encoding="utf-8").read().rstrip("\r\n")
    desired_instances = json.loads(
        os.environ.get(
            "QBITTORRENT_INSTANCES",
            '[{"name":"qBittorrent","host":"http://qbittorrent:8080"}]',
        )
    )
    instances = None
    for attempt in range(30):
        try:
            instances = request(f"{qui}/api/instances", key)
            break
        except (OSError, urllib.error.HTTPError, ValueError):
            if attempt == 29:
                raise SystemExit("Qui API did not become available or rejected the management key")
            time.sleep(10)
    if isinstance(instances, dict):
        instances = instances.get("instances", [])
    sync_instances(qui, key, username, password, desired_instances, instances)


if __name__ == "__main__":
    main()
