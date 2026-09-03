#!/usr/bin/env python3
"""Compare a candidate split render with its resources in a baseline render."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ResourceId = tuple[str, str, str, str]

FLUX_OWNERSHIP_LABELS = {
    "kustomize.toolkit.fluxcd.io/name",
    "kustomize.toolkit.fluxcd.io/namespace",
}


def resource_id(document: dict[str, Any]) -> ResourceId | None:
    metadata = document.get("metadata") or {}
    api_version = document.get("apiVersion")
    kind = document.get("kind")
    name = metadata.get("name")
    if not api_version or not kind or not name:
        return None
    namespace = metadata.get("namespace") or "_cluster_or_default"
    return str(api_version), str(kind), str(namespace), str(name)


def display(value: ResourceId) -> str:
    api_version, kind, namespace, name = value
    return f"{api_version} {kind} {namespace}/{name}"


def load(path: Path) -> tuple[dict[ResourceId, dict[str, Any]], list[str]]:
    resources: dict[ResourceId, dict[str, Any]] = {}
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            documents = yaml.safe_load_all(handle)
            for document in documents:
                if document is None:
                    continue
                if not isinstance(document, dict):
                    errors.append(f"{path}: non-object YAML document")
                    continue
                identity = resource_id(document)
                if identity is None:
                    errors.append(f"{path}: document without complete resource identity")
                    continue
                if identity in resources:
                    errors.append(f"{path}: duplicate resource identity {display(identity)}")
                    continue
                resources[identity] = document
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{path}: unable to load manifests: {exc}")
    return resources, errors


def load_allowed_deltas(
    path: Path | None,
) -> tuple[
    set[ResourceId],
    set[ResourceId],
    dict[ResourceId, str],
    set[ResourceId],
    dict[ResourceId, str],
    list[str],
]:
    if path is None:
        return set(), set(), {}, set(), {}, []

    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        return set(), set(), {}, set(), {}, [f"{path}: unable to load allowed deltas: {exc}"]
    if not isinstance(document, dict):
        return set(), set(), {}, set(), {}, [f"{path}: allowed deltas must be a YAML object"]

    addition_digests: dict[ResourceId, str] = {}
    change_digests: dict[ResourceId, str] = {}

    def parse_entries(key: str) -> set[ResourceId]:
        parsed: set[ResourceId] = set()
        entries = document.get(key) or []
        if not isinstance(entries, list):
            errors.append(f"{path}: {key} must be a list")
            return parsed
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{path}: {key}[{index}] must be an object")
                continue
            required = ("apiVersion", "kind", "namespace", "name")
            if not all(isinstance(entry.get(field), str) and entry[field] for field in required):
                errors.append(f"{path}: {key}[{index}] has an incomplete resource identity")
                continue
            if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                errors.append(f"{path}: {key}[{index}] must document a reason")
                continue
            identity_value: ResourceId = (
                entry["apiVersion"],
                entry["kind"],
                entry["namespace"],
                entry["name"],
            )
            if identity_value in parsed:
                errors.append(f"{path}: duplicate {key} entry {display(identity_value)}")
            parsed.add(identity_value)
            if key in {"allowedIdentityAdditions", "allowedManifestChanges"}:
                digest = entry.get("sha256")
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    errors.append(f"{path}: {key}[{index}] must pin a lowercase SHA-256 digest")
                else:
                    if key == "allowedIdentityAdditions":
                        addition_digests[identity_value] = digest
                    else:
                        change_digests[identity_value] = digest
        return parsed

    additions = parse_entries("allowedIdentityAdditions")
    removals = parse_entries("allowedIdentityRemovals")
    changes = parse_entries("allowedManifestChanges")
    overlap = additions & removals
    for identity_value in sorted(overlap):
        errors.append(f"{path}: identity allowed as both addition and removal: {display(identity_value)}")
    return additions, removals, addition_digests, changes, change_digests, errors


def document_digest(document: dict[str, Any]) -> str:
    normalized_json = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()


def normalized_document(
    document: dict[str, Any], *, ignore_flux_ownership: bool, ignore_flux_prune_protection: bool
) -> dict[str, Any]:
    """Return a copy normalized only for explicitly allowed metadata differences."""
    normalized = copy.deepcopy(document)
    if not ignore_flux_ownership and not ignore_flux_prune_protection:
        return normalized

    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        return normalized
    if ignore_flux_ownership:
        labels = metadata.get("labels")
        if isinstance(labels, dict):
            for label in FLUX_OWNERSHIP_LABELS:
                labels.pop(label, None)
            if not labels:
                metadata.pop("labels", None)

    if ignore_flux_prune_protection:
        annotations = metadata.get("annotations")
        if isinstance(annotations, dict):
            prune_value = annotations.get("kustomize.toolkit.fluxcd.io/prune")
            if prune_value == "disabled":
                annotations.pop("kustomize.toolkit.fluxcd.io/prune")
            if not annotations:
                metadata.pop("annotations", None)
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--exact-namespace",
        action="append",
        default=[],
        help="Require the candidate to contain every baseline identity in this namespace",
    )
    parser.add_argument(
        "--exact-all",
        action="store_true",
        help="Require baseline and candidate to contain exactly the same identities",
    )
    parser.add_argument(
        "--ignore-flux-ownership",
        action="store_true",
        help=(
            "Ignore only Flux's injected kustomization name and namespace labels; "
            "all application metadata and resource specifications remain exact"
        ),
    )
    parser.add_argument(
        "--allowed-deltas",
        type=Path,
        help="YAML file declaring reviewed identity additions and removals",
    )
    parser.add_argument(
        "--ignore-flux-prune-protection",
        action="store_true",
        help="Ignore only an added Flux prune-protection annotation whose value is disabled",
    )
    parser.add_argument("--context", default="candidate render")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline, errors = load(args.baseline)
    candidate, candidate_errors = load(args.candidate)
    errors.extend(candidate_errors)
    (
        allowed_additions,
        allowed_removals,
        addition_digests,
        allowed_changes,
        change_digests,
        delta_errors,
    ) = load_allowed_deltas(args.allowed_deltas)
    errors.extend(delta_errors)

    actual_additions = set(candidate) - set(baseline)
    actual_removals = set(baseline) - set(candidate)
    for identity in sorted(allowed_additions - actual_additions):
        errors.append(f"allowed addition is not present as a render delta: {display(identity)}")
    for identity in sorted(allowed_removals - actual_removals):
        errors.append(f"allowed removal is not present as a render delta: {display(identity)}")
    for identity in sorted(allowed_changes - (set(baseline) & set(candidate))):
        errors.append(f"allowed manifest change is not present in both renders: {display(identity)}")

    used_allowed_changes: set[ResourceId] = set()

    for identity, candidate_document in candidate.items():
        normalized_candidate = normalized_document(
            candidate_document,
            ignore_flux_ownership=args.ignore_flux_ownership,
            ignore_flux_prune_protection=args.ignore_flux_prune_protection,
        )
        baseline_document = baseline.get(identity)
        if baseline_document is None:
            if identity not in allowed_additions:
                errors.append(f"candidate identity is absent from baseline: {display(identity)}")
            elif document_digest(normalized_candidate) != addition_digests.get(identity):
                errors.append(f"reviewed addition manifest digest changed: {display(identity)}")
            continue
        normalized_baseline = normalized_document(
            baseline_document,
            ignore_flux_ownership=args.ignore_flux_ownership,
            ignore_flux_prune_protection=args.ignore_flux_prune_protection,
        )
        if normalized_candidate != normalized_baseline:
            if identity in allowed_changes:
                if document_digest(normalized_candidate) == change_digests.get(identity):
                    used_allowed_changes.add(identity)
                    continue
                errors.append(f"reviewed manifest change digest changed: {display(identity)}")
                continue
            errors.append(f"semantic manifest difference: {display(identity)}")
            baseline_json = json.dumps(normalized_baseline, sort_keys=True, separators=(",", ":"))
            candidate_json = json.dumps(normalized_candidate, sort_keys=True, separators=(",", ":"))
            if baseline_json != candidate_json:
                errors.append("  baseline and candidate normalized JSON differ")

    for identity in sorted(allowed_changes - used_allowed_changes):
        errors.append(f"allowed manifest change is not an actual semantic delta: {display(identity)}")

    for namespace in args.exact_namespace:
        baseline_ids = {identity for identity in baseline if identity[2] == namespace}
        candidate_ids = {identity for identity in candidate if identity[2] == namespace}
        for identity in sorted(baseline_ids - candidate_ids):
            errors.append(f"baseline identity missing from candidate namespace {namespace}: {display(identity)}")
        for identity in sorted(candidate_ids - baseline_ids):
            errors.append(f"unexpected candidate identity in namespace {namespace}: {display(identity)}")

    if args.exact_all:
        for identity in sorted(set(baseline) - set(candidate)):
            if identity not in allowed_removals:
                errors.append(f"baseline identity missing from candidate: {display(identity)}")
        for identity in sorted(set(candidate) - set(baseline)):
            if identity not in allowed_additions:
                errors.append(f"unexpected candidate identity: {display(identity)}")

    if errors:
        print(f"ERROR: render equivalence failed for {args.context}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    delta_summary = ""
    if allowed_additions or allowed_removals or allowed_changes:
        delta_summary = (
            f" with {len(allowed_additions)} reviewed addition(s) and "
            f"{len(allowed_removals)} reviewed removal(s), plus "
            f"{len(allowed_changes)} reviewed manifest change(s)"
        )
    print(
        f"Compared {len(candidate)} candidate resources for {args.context}: "
        f"all candidate manifests match the baseline{delta_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
