#!/usr/bin/env python3
"""Find Kubernetes Secrets by parsed kind and enforce environment SOPS policy."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_RECIPIENT = "age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx"
DEVELOPMENT_RECIPIENT = "age1wzzhdpfdzu5kshctspn7unharyhyg3xja4wenaz4ugaygleme4fs9tdkrt"


@dataclass(frozen=True)
class SecretDocument:
    path: Path
    index: int
    document: dict[str, Any]

    @property
    def display(self) -> str:
        relative = self.path.relative_to(REPO_ROOT)
        return f"{relative}#document-{self.index}"


def yaml_files(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.yaml", "*.yml"):
            for path in root.rglob(pattern):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    yield path


def secret_documents(paths: Iterable[Path]) -> tuple[list[SecretDocument], list[str]]:
    secrets: list[SecretDocument] = []
    errors: list[str] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                documents = list(yaml.safe_load_all(handle))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"unable to parse {path.relative_to(REPO_ROOT)}: {exc}")
            continue
        for index, document in enumerate(documents, start=1):
            if isinstance(document, dict) and document.get("kind") == "Secret":
                secrets.append(SecretDocument(path, index, document))
    return secrets, errors


def contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return "REPLACE_WITH_DEV" in value
    if isinstance(value, dict):
        return any(contains_placeholder(key) or contains_placeholder(child) for key, child in value.items())
    if isinstance(value, list):
        return any(contains_placeholder(child) for child in value)
    return False


def sops_recipients(document: dict[str, Any]) -> set[str]:
    sops = document.get("sops")
    if not isinstance(sops, dict):
        return set()
    age_entries = sops.get("age") or []
    if not isinstance(age_entries, list):
        return set()
    return {
        entry["recipient"]
        for entry in age_entries
        if isinstance(entry, dict) and isinstance(entry.get("recipient"), str)
    }


def validate_environment(
    name: str,
    roots: list[Path],
    expected_recipient: str,
    allow_placeholders: bool,
) -> tuple[list[str], list[str], int]:
    secrets, errors = secret_documents(yaml_files(roots))
    warnings: list[str] = []
    for secret in secrets:
        if allow_placeholders and contains_placeholder(secret.document):
            warnings.append(f"{secret.display}: development placeholder Secret is not encrypted")
            continue
        sops = secret.document.get("sops")
        if not isinstance(sops, dict):
            errors.append(f"{secret.display}: {name} Secret is missing SOPS metadata")
            continue
        if sops.get("encrypted_regex") != "^(data|stringData)$":
            errors.append(f"{secret.display}: SOPS encrypted_regex must protect data and stringData")
        if expected_recipient not in sops_recipients(secret.document):
            errors.append(f"{secret.display}: does not use the {name} age recipient")
    return errors, warnings, len(secrets)


def staged_yaml_paths() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    paths: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = REPO_ROOT / raw_path.decode("utf-8")
        if path.suffix in {".yaml", ".yml"} and path.is_file():
            paths.append(path)
    return paths


def main() -> int:
    production_roots = [REPO_ROOT / "apps/production", REPO_ROOT / "infrastructure/production"]
    development_roots = [REPO_ROOT / "apps/development", REPO_ROOT / "infrastructure/development"]
    base_roots = [REPO_ROOT / "apps/base", REPO_ROOT / "infrastructure/base"]

    production_errors, production_warnings, production_count = validate_environment(
        "production", production_roots, PRODUCTION_RECIPIENT, False
    )
    development_errors, development_warnings, development_count = validate_environment(
        "development", development_roots, DEVELOPMENT_RECIPIENT, True
    )
    base_secrets, base_parse_errors = secret_documents(yaml_files(base_roots))

    errors = production_errors + development_errors + base_parse_errors
    warnings = production_warnings + development_warnings
    for secret in base_secrets:
        errors.append(f"{secret.display}: base layers must not contain Kubernetes Secrets")

    staged_secrets, staged_errors = secret_documents(staged_yaml_paths())
    errors.extend(staged_errors)
    for secret in staged_secrets:
        if not isinstance(secret.document.get("sops"), dict) and not contains_placeholder(secret.document):
            errors.append(f"{secret.display}: staged Secret is neither SOPS-encrypted nor a placeholder")

    print("=========================================")
    print("Secrets Validation")
    print("=========================================")
    print(f"Production Secret documents: {production_count}")
    print(f"Development Secret documents: {development_count}")
    print(f"Base Secret documents: {len(base_secrets)}")
    print(f"Staged Secret documents: {len(staged_secrets)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Secret validation passed with {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
