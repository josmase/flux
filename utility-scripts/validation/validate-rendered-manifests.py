#!/usr/bin/env python3
"""Validate safety invariants on a fully rendered Flux manifest stream."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml


VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
INTENTIONAL_RUNTIME_VARIABLES = {
    ("apps/v1", "Deployment", "media", "transmission"): {"PGID", "PUID"},
}
PRUNE_PROTECTED_KINDS = {
    "Namespace",
    "PersistentVolume",
    "PersistentVolumeClaim",
    "StorageClass",
}


def iter_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(key, str):
                yield f"{child_path}<key>", key
            yield from iter_strings(child, child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")


def identity(document: dict[str, Any]) -> tuple[str, str, str, str] | None:
    api_version = document.get("apiVersion")
    kind = document.get("kind")
    metadata = document.get("metadata") or {}
    name = metadata.get("name")
    if not api_version or not kind or not name:
        return None
    namespace = metadata.get("namespace") or "_cluster_or_default"
    return str(api_version), str(kind), str(namespace), str(name)


def display_identity(resource_id: tuple[str, str, str, str] | None) -> str:
    if resource_id is None:
        return "<document-without-identity>"
    api_version, kind, namespace, name = resource_id
    return f"{api_version} {kind} {namespace}/{name}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="Fully rendered multi-document YAML file")
    parser.add_argument("--context", default="rendered manifests")
    parser.add_argument(
        "--allow-runtime-variable",
        action="append",
        default=[],
        metavar="NAME",
        help="Allow an intentional runtime ${NAME} placeholder; may be repeated",
    )
    parser.add_argument(
        "--require-local-pvc-references",
        action="store_true",
        help="Require every direct Pod workload PVC reference to exist in this manifest stream",
    )
    parser.add_argument(
        "--require-prune-protection",
        action="store_true",
        help="Require Namespaces, StorageClasses, PVs, and PVCs to disable Flux pruning",
    )
    return parser.parse_args()


def pod_spec(document: dict[str, Any]) -> dict[str, Any] | None:
    kind = document.get("kind")
    spec = document.get("spec") or {}
    if kind == "Pod":
        return spec if isinstance(spec, dict) else None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job"}:
        template = spec.get("template") or {}
        value = template.get("spec") if isinstance(template, dict) else None
        return value if isinstance(value, dict) else None
    if kind == "CronJob":
        job_template = spec.get("jobTemplate") or {}
        job_spec = job_template.get("spec") or {} if isinstance(job_template, dict) else {}
        template = job_spec.get("template") or {} if isinstance(job_spec, dict) else {}
        value = template.get("spec") if isinstance(template, dict) else None
        return value if isinstance(value, dict) else None
    return None


def main() -> int:
    args = parse_args()
    globally_allowed_runtime_variables = set(args.allow_runtime_variable)

    try:
        with args.manifest.open("r", encoding="utf-8") as handle:
            documents = [doc for doc in yaml.safe_load_all(handle) if doc is not None]
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: unable to parse {args.context}: {exc}", file=sys.stderr)
        return 1

    identities: list[tuple[str, str, str, str]] = []
    errors: list[str] = []

    if not documents:
        errors.append("manifest stream is empty")

    for document in documents:
        if not isinstance(document, dict):
            errors.append(f"non-object YAML document found: {type(document).__name__}")
            continue

        resource_id = identity(document)
        if resource_id is None:
            errors.append("document is missing apiVersion, kind, or metadata.name")
        else:
            identities.append(resource_id)

        if args.require_prune_protection and document.get("kind") in PRUNE_PROTECTED_KINDS:
            annotations = (document.get("metadata") or {}).get("annotations") or {}
            if annotations.get("kustomize.toolkit.fluxcd.io/prune") != "disabled":
                errors.append(f"{display_identity(resource_id)}: missing Flux prune protection")

        allowed_runtime_variables = globally_allowed_runtime_variables | INTENTIONAL_RUNTIME_VARIABLES.get(
            resource_id, set()
        )
        for field_path, value in iter_strings(document):
            for variable in VARIABLE_PATTERN.findall(value):
                if variable not in allowed_runtime_variables:
                    errors.append(
                        f"{display_identity(resource_id)}: unresolved ${{{variable}}} at {field_path}"
                    )

    duplicate_identities = [resource_id for resource_id, count in Counter(identities).items() if count > 1]
    for resource_id in sorted(duplicate_identities):
        errors.append(f"duplicate resource identity: {display_identity(resource_id)}")

    if args.require_local_pvc_references:
        pvc_identities = {
            (resource_id[2], resource_id[3])
            for resource_id in identities
            if resource_id[1] == "PersistentVolumeClaim"
        }
        for document in documents:
            if not isinstance(document, dict):
                continue
            resource_id = identity(document)
            workload_pod_spec = pod_spec(document)
            if resource_id is None or workload_pod_spec is None:
                continue
            namespace = resource_id[2]
            volumes = workload_pod_spec.get("volumes") or []
            if not isinstance(volumes, list):
                continue
            for index, volume in enumerate(volumes):
                if not isinstance(volume, dict):
                    continue
                claim = volume.get("persistentVolumeClaim")
                if not isinstance(claim, dict) or not claim.get("claimName"):
                    continue
                claim_name = str(claim["claimName"])
                if (namespace, claim_name) not in pvc_identities:
                    errors.append(
                        f"{display_identity(resource_id)}: volume {index} references missing "
                        f"PVC {namespace}/{claim_name}"
                    )

    if errors:
        print(f"ERROR: safety validation failed for {args.context}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(documents)} documents for {args.context}: "
        "no duplicate identities, unsafe placeholders, or broken required references"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
