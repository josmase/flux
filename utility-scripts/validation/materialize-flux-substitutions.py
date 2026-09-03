#!/usr/bin/env python3
"""Materialize a Flux Kustomization's local ConfigMap substitutions for dry-run builds."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml


def load_documents(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            documents = [document for document in yaml.safe_load_all(handle) if document is not None]
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to load {path}: {exc}") from exc
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError(f"{path} contains a non-object YAML document")
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kustomization-file", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--cluster-vars", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        documents = load_documents(args.kustomization_file)
        var_documents = load_documents(args.cluster_vars)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    matches = [
        document
        for document in documents
        if document.get("kind") == "Kustomization"
        and (document.get("metadata") or {}).get("name") == args.name
    ]
    if len(matches) != 1:
        print(
            f"ERROR: expected exactly one Kustomization/{args.name} in "
            f"{args.kustomization_file}; found {len(matches)}",
            file=sys.stderr,
        )
        return 1

    config_maps = [
        document
        for document in var_documents
        if document.get("kind") == "ConfigMap"
        and (document.get("metadata") or {}).get("name") == "cluster-vars"
    ]
    if len(config_maps) != 1:
        print(
            f"ERROR: expected exactly one ConfigMap/cluster-vars in {args.cluster_vars}",
            file=sys.stderr,
        )
        return 1

    values = config_maps[0].get("data") or {}
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in values.items()
    ):
        print("ERROR: ConfigMap/cluster-vars data must contain only string values", file=sys.stderr)
        return 1

    materialized = copy.deepcopy(matches[0])
    spec = materialized.setdefault("spec", {})
    post_build = spec.setdefault("postBuild", {})
    inline = post_build.get("substitute") or {}
    if not isinstance(inline, dict):
        print(f"ERROR: Kustomization/{args.name} postBuild.substitute must be a map", file=sys.stderr)
        return 1

    # Flux gives explicit inline substitutions precedence over substituteFrom.
    post_build["substitute"] = {**values, **inline}
    post_build.pop("substituteFrom", None)
    yaml.safe_dump(materialized, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
