#!/usr/bin/env python3
"""Pin each production domain's exact rendered resource membership."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml


def identity(document: dict[str, Any]) -> str | None:
    metadata = document.get("metadata") or {}
    api_version = document.get("apiVersion")
    kind = document.get("kind")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not api_version or not kind or not name:
        return None
    namespace = metadata.get("namespace") or "_cluster_or_default"
    return f"{api_version}|{kind}|{namespace}|{name}"


def load_documents(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        documents = [document for document in yaml.safe_load_all(handle) if document is not None]
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError(f"{path} contains a non-object YAML document")
    return documents


def inventory_digest(path: Path) -> tuple[int, str]:
    documents = load_documents(path)
    identities = [identity(document) for document in documents]
    if any(value is None for value in identities):
        raise ValueError(f"{path} contains a document without a complete identity")
    concrete = [value for value in identities if value is not None]
    if len(concrete) != len(set(concrete)):
        raise ValueError(f"{path} contains duplicate identities")
    payload = "\n".join(sorted(concrete)).encode("utf-8")
    return len(concrete), hashlib.sha256(payload).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--inventory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count, digest = inventory_digest(args.manifest)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"ERROR: unable to inventory {args.domain}: {exc}", file=sys.stderr)
        return 1

    if args.inventory is None:
        print(f"  {args.domain}:")
        print(f"    count: {count}")
        print(f"    sha256: {digest}")
        return 0

    try:
        with args.inventory.open("r", encoding="utf-8") as handle:
            inventory = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: unable to load {args.inventory}: {exc}", file=sys.stderr)
        return 1
    domains = inventory.get("domains") if isinstance(inventory, dict) else None
    expected = domains.get(args.domain) if isinstance(domains, dict) else None
    if not isinstance(expected, dict):
        print(f"ERROR: {args.domain} is missing from {args.inventory}", file=sys.stderr)
        return 1
    if expected.get("count") != count or expected.get("sha256") != digest:
        print(
            f"ERROR: {args.domain} membership changed: expected "
            f"count={expected.get('count')} sha256={expected.get('sha256')}, "
            f"found count={count} sha256={digest}",
            file=sys.stderr,
        )
        return 1
    print(f"Validated {args.domain} membership: {count} resources, sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
