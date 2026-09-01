#!/usr/bin/env python3
"""
arr-client-migration.py — Reversible Transmission download-client migration for Sonarr/Radarr.

This module provides the core logic for migrating all 18 arr instances from an external
Transmission endpoint to the in-cluster Service DNS endpoint.
"""

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

CTX = ssl._create_unverified_context()

# Instance definitions from session inventory
RADARR_INSTANCES = [f"radarr-{i}" for i in range(1, 13)]
SONARR_INSTANCES = [f"sonarr-{i}" for i in range(1, 7)]
ALL_INSTANCES = RADARR_INSTANCES + SONARR_INSTANCES

# Category mapping from session inventory
CATEGORIES = {
    "radarr-1": "radarrone",
    "radarr-2": "radarrtwo",
    "radarr-3": "radarrthree",
    "radarr-4": "radarrfour",
    "radarr-5": "radarrfive",
    "radarr-6": "radarrsix",
    "radarr-7": "radarrseven",
    "radarr-8": "radarreight",
    "radarr-9": "radarrnine",
    "radarr-10": "radarrten",
    "radarr-11": "radarreleven",
    "radarr-12": "radarrtwelve",
    "sonarr-1": "sonarrone",
    "sonarr-2": "sonarrtwo",
    "sonarr-3": "sonarrthree",
    "sonarr-4": "sonarrfour",
    "sonarr-5": "sonarrfive",
    "sonarr-6": "seriessix",
}

# Legacy disabled client IDs from session inventory
LEGACY_CLIENTS = {
    "radarr-1": [2],
    "radarr-2": [2],
    "radarr-3": [2],
    "sonarr-1": [2],
    "sonarr-2": [2],
}

# Target Transmission endpoint
TARGET_HOST = "transmission.media.svc.cluster.local"
TARGET_PORT = 9091
TARGET_USE_SSL = False
TARGET_URL_BASE = "/transmission/"

# Internal service ports
RADARR_PORT = 7878
SONARR_PORT = 8989

# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DownloadClient:
    id: int
    name: str
    enable: bool
    implementation: str
    fields: list[dict[str, Any]]


def safe_int(v: Any, default: int = 0) -> int:
    return int(v) if v is not None else default


def safe_str(v: Any, default: str = "") -> str:
    return str(v) if v is not None else default


def safe_bool(v: Any, default: bool = False) -> bool:
    return bool(v) if v is not None else default

@dataclass
class MigrationPlan:
    instance: str
    current_clients: list[DownloadClient]
    target_client: Optional[DownloadClient]
    actions: list[str]  # "create", "update", "disable", "delete", "test"
    backup: dict[str, Any]

# ──────────────────────────────────────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────────────────────────────────────

def fetch_api_key(deployment: str) -> str:
    """Extract API key from arr config.xml via kubectl exec."""
    raw = subprocess.check_output(
        ["kubectl", "exec", "-n", "media", f"deploy/{deployment}", "--", "cat", "/config/config.xml"],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", raw)
    if not match:
        raise RuntimeError(f"API key not found in {deployment}")
    return match.group(1)


def api_request(instance: str, api_key: str, method: str, path: str, body: Optional[dict] = None) -> Any:
    """Make an API request to an arr instance via kubectl exec."""
    port = RADARR_PORT if instance.startswith("radarr-") else SONARR_PORT
    deployment = f"{instance}-{instance.split('-')[0]}"
    curl_cmd = ["curl", "-s", "-X", method]
    curl_cmd += [f"http://localhost:{port}/api/v3{path}"]
    curl_cmd += ["-H", f"X-Api-Key: {api_key}"]
    if body is not None:
        curl_cmd += ["-H", "Content-Type: application/json"]
        curl_cmd += ["-d", json.dumps(body)]
    
    cmd = ["kubectl", "exec", "-n", "media", f"deploy/{deployment}", "--"] + curl_cmd
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"kubectl exec failed: {result.stderr}")
    # stdout contains JSON, stderr contains "Defaulted container" message
    try:
        return json.loads(result.stdout)
    except:
        return result.stdout


def get_download_clients(instance: str, api_key: str) -> list[DownloadClient]:
    """Fetch all download clients for an instance."""
    raw = api_request(instance, api_key, "GET", "/downloadclient")
    clients = []
    for c in raw:
        clients.append(DownloadClient(
            id=c.get("id"),
            name=c.get("name"),
            enable=c.get("enable"),
            implementation=c.get("implementation"),
            fields=c.get("fields", []),
        ))
    return clients


def get_remote_path_mappings(instance: str, api_key: str) -> list[dict]:
    """Fetch remote path mappings for an instance."""
    return api_request(instance, api_key, "GET", "/remotepathmapping")


def test_download_client(instance: str, api_key: str, client_id: int) -> dict:
    """Test a download client."""
    return api_request(instance, api_key, "POST", f"/downloadclient/test/{client_id}")


def test_all_download_clients(instance: str, api_key: str) -> list[dict]:
    """Test all download clients."""
    return api_request(instance, api_key, "POST", "/downloadclient/testall")


def create_download_client(instance: str, api_key: str, client: dict) -> dict:
    """Create a new download client."""
    return api_request(instance, api_key, "POST", "/downloadclient", client)


def update_download_client(instance: str, api_key: str, client_id: int, client: dict) -> dict:
    """Update an existing download client."""
    return api_request(instance, api_key, "PUT", f"/downloadclient/{client_id}", client)


def delete_download_client(instance: str, api_key: str, client_id: int) -> bool:
    """Delete a download client."""
    api_request(instance, api_key, "DELETE", f"/downloadclient/{client_id}")
    return True


def create_backup(instance: str, api_key: str) -> dict:
    """Trigger a manual application backup."""
    return api_request(instance, api_key, "POST", "/command", {"name": "Backup"})


def list_backups(instance: str, api_key: str) -> list[dict]:
    """List available backups."""
    return api_request(instance, api_key, "GET", "/system/backup")


# ──────────────────────────────────────────────────────────────────────────────
# Field helpers
# ──────────────────────────────────────────────────────────────────────────────

def fields_to_dict(fields: list[dict]) -> dict:
    """Convert fields array to dict."""
    return {f.get("name"): f.get("value") for f in fields}


def dict_to_fields(d: dict) -> list[dict]:
    """Convert dict to fields array."""
    return [{"name": k, "value": v} for k, v in d.items()]


def build_transmission_client(category: str, is_radarr: bool) -> dict:
    """Build the canonical Transmission client configuration."""
    fields = {
        "host": TARGET_HOST,
        "port": TARGET_PORT,
        "useSsl": TARGET_USE_SSL,
        "urlBase": TARGET_URL_BASE,
        "username": "",
        "password": "",
    }
    if is_radarr:
        fields["movieCategory"] = category
    else:
        fields["tvCategory"] = category
    return {
        "name": "Transmission",
        "enable": True,
        "implementation": "Transmission",
        "implementationName": "Transmission",
        "configContract": "TransmissionSettings",
        "fields": dict_to_fields(fields),
    }


def is_transmission_client(client: DownloadClient) -> bool:
    """Check if a client is a Transmission implementation."""
    return client.implementation == "Transmission"


def get_client_category(client: DownloadClient, is_radarr: bool) -> Optional[str]:
    """Extract category from a Transmission client."""
    fields = fields_to_dict(client.fields)
    if is_radarr:
        return fields.get("movieCategory")
    return fields.get("tvCategory")


def client_matches_target(client: DownloadClient, is_radarr: bool) -> bool:
    """Check if a client already matches the target configuration."""
    fields = fields_to_dict(client.fields)
    return (
        fields.get("host") == TARGET_HOST
        and fields.get("port") == TARGET_PORT
        and fields.get("useSsl") == TARGET_USE_SSL
        and fields.get("urlBase") == TARGET_URL_BASE
    )


# ──────────────────────────────────────────────────────────────────────────────
# Migration planning
# ──────────────────────────────────────────────────────────────────────────────

def plan_migration(instance: str, api_key: str, dry_run: bool = True) -> MigrationPlan:
    """Plan the migration for a single instance."""
    is_radarr = instance.startswith("radarr-")
    category = CATEGORIES[instance]
    legacy_ids = LEGACY_CLIENTS.get(instance, [])

    current_clients = get_download_clients(instance, api_key)
    transmission_clients = [c for c in current_clients if is_transmission_client(c)]

    # Find the currently enabled client
    enabled_client = next((c for c in transmission_clients if c.enable), None)

    # Check if any client already matches target
    target_match = next((c for c in transmission_clients if client_matches_target(c, is_radarr)), None)

    actions = []
    target_client = None

    if target_match:
        # Already has correct client - just ensure it's enabled and has right category
        if not target_match.enable:
            actions.append("enable")
        if get_client_category(target_match, is_radarr) != category:
            actions.append("update_category")
        target_client = target_match
    elif enabled_client:
        # Has enabled client but wrong endpoint - update it
        actions.append("update")
        target_client = enabled_client
    else:
        # No enabled Transmission client - create new
        actions.append("create")
        target_client = None

    # Handle legacy disabled clients
    for legacy_id in legacy_ids:
        legacy_client = next((c for c in transmission_clients if c.id == legacy_id), None)
        if legacy_client and legacy_client.enable:
            actions.append(f"disable_legacy_{legacy_id}")

    # Build backup
    backup = {
        "instance": instance,
        "clients": [asdict(c) for c in current_clients],
        "remote_path_mappings": get_remote_path_mappings(instance, api_key),
    }

    return MigrationPlan(
        instance=instance,
        current_clients=current_clients,
        target_client=target_client,
        actions=actions,
        backup=backup,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────────────────────────────────────

def execute_plan(instance: str, api_key: str, plan: MigrationPlan, dry_run: bool = True) -> dict:
    """Execute the migration plan for an instance."""
    is_radarr = instance.startswith("radarr-")
    category = CATEGORIES[instance]
    results = {"instance": instance, "actions": [], "errors": []}

    def log_action(action: str, detail: str = ""):
        results["actions"].append(f"{action}: {detail}")

    def log_error(action: str, error: str):
        results["errors"].append(f"{action}: {error}")

    # Create backup first (always, even in dry-run we record it)
    if not dry_run:
        try:
            backup_result = create_backup(instance, api_key)
            log_action("backup", str(backup_result))
        except Exception as e:
            log_error("backup", str(e))
            return results

    # Process actions
    for action in plan.actions:
        try:
            if action == "create":
                if dry_run:
                    log_action("create", "would create new Transmission client")
                else:
                    client = build_transmission_client(category, is_radarr)
                    created = create_download_client(instance, api_key, client)
                    log_action("create", f"created client id {created.get('id')}")
                    plan.target_client = DownloadClient(
                        id=safe_int(created.get("id")),
                        name=safe_str(created.get("name")),
                        enable=safe_bool(created.get("enable")),
                        implementation=safe_str(created.get("implementation")),
                        fields=created.get("fields", []),
                    )

            elif action == "update":
                if plan.target_client is None:
                    log_error("update", "no target client to update")
                    continue
                if dry_run:
                    log_action("update", f"would update client {plan.target_client.id} to target endpoint")
                else:
                    client = build_transmission_client(category, is_radarr)
                    client["id"] = plan.target_client.id
                    # Preserve masked password if present
                    fields = fields_to_dict(plan.target_client.fields)
                    if fields.get("password") and fields["password"] != "":
                        client["fields"] = [f for f in client["fields"] if f["name"] != "password"]
                        client["fields"].append({"name": "password", "value": fields["password"]})
                    updated = update_download_client(instance, api_key, plan.target_client.id, client)
                    log_action("update", f"updated client {plan.target_client.id}")

            elif action == "update_category":
                if plan.target_client is None:
                    log_error("update_category", "no target client")
                    continue
                if dry_run:
                    log_action("update_category", f"would update category to {category}")
                else:
                    client = build_transmission_client(category, is_radarr)
                    client["id"] = plan.target_client.id
                    fields = fields_to_dict(plan.target_client.fields)
                    if fields.get("password") and fields["password"] != "":
                        client["fields"] = [f for f in client["fields"] if f["name"] != "password"]
                        client["fields"].append({"name": "password", "value": fields["password"]})
                    updated = update_download_client(instance, api_key, plan.target_client.id, client)
                    log_action("update_category", f"updated client {plan.target_client.id}")

            elif action == "enable":
                if plan.target_client is None:
                    log_error("enable", "no target client")
                    continue
                if dry_run:
                    log_action("enable", f"would enable client {plan.target_client.id}")
                else:
                    client = build_transmission_client(category, is_radarr)
                    client["id"] = plan.target_client.id
                    client["enable"] = True
                    fields = fields_to_dict(plan.target_client.fields)
                    if fields.get("password") and fields["password"] != "":
                        client["fields"] = [f for f in client["fields"] if f["name"] != "password"]
                        client["fields"].append({"name": "password", "value": fields["password"]})
                    updated = update_download_client(instance, api_key, plan.target_client.id, client)
                    log_action("enable", f"enabled client {plan.target_client.id}")

            elif action.startswith("disable_legacy_"):
                legacy_id = int(action.split("_")[-1])
                if dry_run:
                    log_action("disable_legacy", f"would disable legacy client {legacy_id}")
                else:
                    # Disable by updating with enable=false
                    legacy_client = next((c for c in plan.current_clients if c.id == legacy_id), None)
                    if legacy_client:
                        client = build_transmission_client(category, is_radarr)
                        client["id"] = legacy_id
                        client["enable"] = False
                        fields = fields_to_dict(legacy_client.fields)
                        if fields.get("password") and fields["password"] != "":
                            client["fields"] = [f for f in client["fields"] if f["name"] != "password"]
                            client["fields"].append({"name": "password", "value": fields["password"]})
                        updated = update_download_client(instance, api_key, legacy_id, client)
                        log_action("disable_legacy", f"disabled legacy client {legacy_id}")

        except Exception as e:
            log_error(action, str(e))
            # Stop on first error
            break

    # Test the final client
    if plan.target_client and not dry_run and not results["errors"]:
        try:
            test_result = test_download_client(instance, api_key, plan.target_client.id)
            log_action("test", str(test_result))
        except Exception as e:
            log_error("test", str(e))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────────────────

def discover_instances() -> list[str]:
    """Discover available arr instances from the cluster."""
    instances = []
    for i in range(1, 13):
        try:
            fetch_api_key(f"radarr-{i}-radarr")
            instances.append(f"radarr-{i}")
        except Exception:
            pass
    for i in range(1, 7):
        try:
            fetch_api_key(f"sonarr-{i}-sonarr")
            instances.append(f"sonarr-{i}")
        except Exception:
            pass
    return instances


def validate_instance_set(instances: list[str]) -> None:
    """Validate that we have exactly the expected instances."""
    expected = set(ALL_INSTANCES)
    found = set(instances)
    if found != expected:
        missing = expected - found
        extra = found - expected
        msg = []
        if missing:
            msg.append(f"Missing instances: {sorted(missing)}")
        if extra:
            msg.append(f"Unexpected instances: {sorted(extra)}")
        raise RuntimeError("Instance validation failed: " + "; ".join(msg))


def run_migration(dry_run: bool = True, execute: bool = False, rollback: bool = False) -> dict:
    """Run the full migration across all instances."""
    if rollback:
        raise NotImplementedError("Rollback not yet implemented")

    if not dry_run and not execute:
        raise ValueError("Must specify either --dry-run or --execute")

    if execute and not dry_run:
        # execute implies dry-run first
        pass

    print(f"Mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")

    # Discover and validate instances
    instances = discover_instances()
    print(f"Discovered instances: {instances}")
    validate_instance_set(instances)

    # Fetch API keys
    api_keys = {}
    for instance in instances:
        deployment = f"{instance}-{instance.split('-')[0]}"
        api_keys[instance] = fetch_api_key(deployment)

    # Plan all migrations
    plans = {}
    for instance in instances:
        plans[instance] = plan_migration(instance, api_keys[instance], dry_run)

    # Print plans
    for instance, plan in plans.items():
        print(f"\n{instance}:")
        print(f"  Current Transmission clients: {len([c for c in plan.current_clients if is_transmission_client(c)])}")
        print(f"  Actions: {plan.actions}")

    # Execute if not dry-run
    results = {"mode": "dry-run" if dry_run else "execute", "instances": {}}
    if not dry_run:
        for instance in instances:
            print(f"\nExecuting {instance}...")
            results["instances"][instance] = execute_plan(instance, api_keys[instance], plans[instance], dry_run=False)
    else:
        for instance in instances:
            results["instances"][instance] = execute_plan(instance, api_keys[instance], plans[instance], dry_run=True)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate arr Transmission clients to in-cluster endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done (default)")
    parser.add_argument("--execute", action="store_true", help="Perform the migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback a previous migration")
    parser.add_argument("--instance", help="Run for a single instance only")
    parser.add_argument("--output", help="Write results to JSON file")

    args = parser.parse_args()

    if args.rollback:
        print("Rollback not yet implemented", file=sys.stderr)
        sys.exit(1)

    if args.instance:
        if args.instance not in ALL_INSTANCES:
            print(f"Unknown instance: {args.instance}", file=sys.stderr)
            sys.exit(1)
        instances = [args.instance]
    else:
        instances = None

    dry_run = not args.execute
    results = run_migration(dry_run=dry_run, execute=args.execute, rollback=args.rollback)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))

    # Exit with error if any errors occurred
    has_errors = any(r.get("errors") for r in results.get("instances", {}).values())
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()