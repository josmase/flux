#!/usr/bin/env python3
"""Validate the inactive, prune-safe production Flux ownership handoff state."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_FILE = REPO_ROOT / "clusters/production/apps-domains.yaml"
LEGACY_FILE = REPO_ROOT / "clusters/production/apps.yaml"
VARS_FILE = REPO_ROOT / "clusters/production/cluster-vars.yaml"
BOOTSTRAP_KUSTOMIZATION = REPO_ROOT / "clusters/production/flux-system/kustomization.yaml"

EXPECTED_DOMAINS: dict[str, tuple[str, set[str]]] = {
    "apps-storage": ("./apps/production/storage", {"infra-configs"}),
    "apps-ops": ("./apps/production/ops", {"infra-configs"}),
    "apps-observability": ("./apps/production/observability", {"infra-configs"}),
    "apps-media-foundation": ("./apps/production/media/foundation", {"apps-storage"}),
    "apps-media-download": (
        "./apps/production/media/download",
        {"apps-media-foundation"},
    ),
    "apps-media-arr": ("./apps/production/media/arr", {"apps-media-foundation"}),
    "apps-media-playback": (
        "./apps/production/media/playback",
        {"apps-media-foundation"},
    ),
    "apps-photos": ("./apps/production/photos", {"apps-storage"}),
    "apps-gitlab": ("./apps/production/developer-platform/gitlab", {"infra-configs"}),
    "apps-artifacts": (
        "./apps/production/developer-platform/artifacts",
        {"infra-configs"},
    ),
    "apps-services": ("./apps/production/services", {"apps-storage"}),
    "apps-home": ("./apps/production/home", {"infra-configs"}),
}

# Ownership is deliberately transferred one domain at a time. This revision
# activates only the small, non-data-bearing ops domain; every other candidate
# remains an inert, orphan-safe definition until its own reviewed revision.
ACTIVE_DOMAINS = {"apps-ops"}

EXPECTED_CLUSTER_VARS = {
    "CERT_SECRET_EXTERNAL": "hejsan-xyz-tls",
    "CERT_SECRET_INTERNAL": "local-hejsan-xyz-tls",
    "DOMAIN_EXTERNAL": "hejsan.xyz",
    "DOMAIN_INTERNAL": "local.hejsan.xyz",
    "ENVIRONMENT": "production",
    "LETSENCRYPT_SERVER": "https://acme-v02.api.letsencrypt.org/directory",
    "LIVE_ENDPOINT": "http://netboot-assets.local.hejsan.xyz",
    "STORAGE_CLASS": "longhorn",
}


def load_documents(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            documents = [document for document in yaml.safe_load_all(handle) if document is not None]
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to load {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError(f"{path.relative_to(REPO_ROOT)} contains a non-object YAML document")
    return documents


def one_document(path: Path) -> dict[str, Any]:
    documents = load_documents(path)
    if len(documents) != 1:
        raise ValueError(
            f"{path.relative_to(REPO_ROOT)} must contain exactly one document; found {len(documents)}"
        )
    return documents[0]


def kustomization_name(document: dict[str, Any]) -> str | None:
    if document.get("apiVersion") != "kustomize.toolkit.fluxcd.io/v1":
        return None
    if document.get("kind") != "Kustomization":
        return None
    metadata = document.get("metadata") or {}
    return metadata.get("name") if isinstance(metadata, dict) else None


def validate_domain(
    name: str, document: dict[str, Any], expected_path: str, expected_dependencies: set[str]
) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    spec = document.get("spec") or {}
    prefix = f"{DOMAIN_FILE.relative_to(REPO_ROOT)}: {name}"

    if metadata.get("namespace") != "flux-system":
        errors.append(f"{prefix} must be in flux-system")
    expected_suspend = name not in ACTIVE_DOMAINS
    if spec.get("suspend") is not expected_suspend:
        state = "active" if name in ACTIVE_DOMAINS else "suspended"
        errors.append(f"{prefix} must remain {state} at this ownership-transfer stage")
    if spec.get("prune") is not False:
        errors.append(f"{prefix} must use prune: false during ownership transfer")
    if spec.get("deletionPolicy") != "Orphan":
        errors.append(f"{prefix} must use deletionPolicy: Orphan")
    if "force" in spec:
        errors.append(f"{prefix} must not set force")
    if spec.get("wait") is not True:
        errors.append(f"{prefix} must use wait: true")
    if not spec.get("timeout"):
        errors.append(f"{prefix} must declare a bounded timeout")
    if spec.get("path") != expected_path:
        errors.append(f"{prefix} path must be {expected_path}, found {spec.get('path')!r}")
    else:
        root = REPO_ROOT / expected_path.removeprefix("./")
        if not (root / "kustomization.yaml").is_file():
            errors.append(f"{prefix} path is not an independently buildable root")

    source_ref = spec.get("sourceRef") or {}
    if source_ref != {"kind": "GitRepository", "name": "flux-system"}:
        errors.append(f"{prefix} must use GitRepository/flux-system")

    dependencies = spec.get("dependsOn") or []
    dependency_names = {
        item.get("name") for item in dependencies if isinstance(item, dict) and item.get("name")
    }
    if len(dependency_names) != len(dependencies):
        errors.append(f"{prefix} contains an invalid or duplicate dependency")
    if dependency_names != expected_dependencies:
        errors.append(
            f"{prefix} dependencies must be {sorted(expected_dependencies)}, "
            f"found {sorted(dependency_names)}"
        )

    decryption = spec.get("decryption") or {}
    if decryption != {"provider": "sops", "secretRef": {"name": "sops-age"}}:
        errors.append(f"{prefix} must use the production SOPS age key")

    post_build = spec.get("postBuild") or {}
    expected_refs = [{"kind": "ConfigMap", "name": "cluster-vars"}]
    if post_build.get("substituteFrom") != expected_refs:
        errors.append(f"{prefix} must require ConfigMap/cluster-vars")
    substitute = post_build.get("substitute")
    if name == "apps-media-download":
        if substitute != {"TRANSMISSION_PEER_IP": "192.168.1.184"}:
            errors.append(f"{prefix} must own only the Transmission peer IP substitution")
    elif substitute:
        errors.append(f"{prefix} must not duplicate shared inline substitutions")

    return errors


def validate_dependency_graph() -> list[str]:
    errors: list[str] = []
    domain_names = set(EXPECTED_DOMAINS)
    graph = {
        name: dependencies & domain_names
        for name, (_, dependencies) in EXPECTED_DOMAINS.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            errors.append(f"domain dependency graph contains a cycle at {name}")
            return
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for domain_name in graph:
        visit(domain_name)
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        domain_documents = load_documents(DOMAIN_FILE)
        legacy = one_document(LEGACY_FILE)
        cluster_vars = one_document(VARS_FILE)
        bootstrap = one_document(BOOTSTRAP_KUSTOMIZATION)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    domains: dict[str, dict[str, Any]] = {}
    for document in domain_documents:
        name = kustomization_name(document)
        if not name:
            errors.append(f"{DOMAIN_FILE.relative_to(REPO_ROOT)} contains a non-Flux Kustomization")
            continue
        if name in domains:
            errors.append(f"duplicate domain Kustomization {name}")
            continue
        domains[name] = document

    missing = set(EXPECTED_DOMAINS) - set(domains)
    unexpected = set(domains) - set(EXPECTED_DOMAINS)
    for name in sorted(missing):
        errors.append(f"missing domain Kustomization {name}")
    for name in sorted(unexpected):
        errors.append(f"unexpected domain Kustomization {name}")
    for name, (path, dependencies) in EXPECTED_DOMAINS.items():
        if name in domains:
            errors.extend(validate_domain(name, domains[name], path, dependencies))
    errors.extend(validate_dependency_graph())

    legacy_spec = legacy.get("spec") or {}
    if kustomization_name(legacy) != "apps":
        errors.append(f"{LEGACY_FILE.relative_to(REPO_ROOT)} must define Kustomization/apps")
    if legacy_spec.get("path") != "./apps/production":
        errors.append("legacy apps path must remain ./apps/production until ownership transfer")
    if legacy_spec.get("prune") is not False:
        errors.append("legacy Kustomization/apps must use prune: false before handoff")
    if legacy_spec.get("deletionPolicy") != "Orphan":
        errors.append("legacy Kustomization/apps must use deletionPolicy: Orphan before handoff")
    if "force" in legacy_spec:
        errors.append("legacy Kustomization/apps must not use global force")
    if legacy_spec.get("suspend") is not True:
        errors.append("legacy Kustomization/apps must remain suspended during ownership transfer")

    cluster_metadata = cluster_vars.get("metadata") or {}
    if cluster_vars.get("kind") != "ConfigMap" or cluster_metadata.get("name") != "cluster-vars":
        errors.append(f"{VARS_FILE.relative_to(REPO_ROOT)} must define ConfigMap/cluster-vars")
    if cluster_metadata.get("namespace") != "flux-system":
        errors.append("ConfigMap/cluster-vars must be in flux-system")
    labels = cluster_metadata.get("labels") or {}
    if labels.get("reconcile.fluxcd.io/watch") != "Enabled":
        errors.append("ConfigMap/cluster-vars must trigger reconciliation of consumers")
    if cluster_vars.get("data") != EXPECTED_CLUSTER_VARS:
        errors.append("ConfigMap/cluster-vars data differs from the reviewed production contract")

    legacy_substitute = (legacy_spec.get("postBuild") or {}).get("substitute") or {}
    legacy_common = {
        key: value for key, value in legacy_substitute.items() if key != "TRANSMISSION_PEER_IP"
    }
    if legacy_common != EXPECTED_CLUSTER_VARS:
        errors.append("legacy inline substitutions differ from ConfigMap/cluster-vars")
    if legacy_substitute.get("TRANSMISSION_PEER_IP") != "192.168.1.184":
        errors.append("legacy Transmission peer IP differs from apps-media-download")

    patches = bootstrap.get("patches") or []
    strict_gate = "--feature-gates=StrictPostBuildSubstitutions=true"
    strict_patches = []
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        target = patch.get("target") or {}
        if target != {
            "group": "apps",
            "version": "v1",
            "kind": "Deployment",
            "name": "kustomize-controller",
            "namespace": "flux-system",
        }:
            continue
        try:
            operations = yaml.safe_load(patch.get("patch", ""))
        except yaml.YAMLError:
            operations = None
        if isinstance(operations, list) and any(
            isinstance(operation, dict) and operation.get("value") == strict_gate
            for operation in operations
        ):
            strict_patches.append(operations)
    if len(strict_patches) != 1:
        errors.append("Flux bootstrap overlay must contain exactly one strict-substitution patch")
    else:
        expected_operations = [
            {
                "op": "test",
                "path": "/spec/template/spec/containers/0/name",
                "value": "manager",
            },
            {
                "op": "add",
                "path": "/spec/template/spec/containers/0/args/-",
                "value": strict_gate,
            },
        ]
        if strict_patches[0] != expected_operations:
            errors.append("strict-substitution patch must guard the generated container index")

    if errors:
        print("ERROR: production Flux migration safety validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(domains)} production domain Kustomizations with "
        f"{len(ACTIVE_DOMAINS)} active owner: legacy ownership remains suspended and orphan-safe"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
