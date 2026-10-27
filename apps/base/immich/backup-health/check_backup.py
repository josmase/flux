#!/usr/bin/env python3
"""Read-only validator for Immich's nightly database backup artifacts."""

from __future__ import annotations

import argparse
import gzip
import re
import sys
import time
from pathlib import Path

FINAL_ARCHIVE = re.compile(r"^immich-db-backup-.+\.sql\.gz$")
TEMP_ARCHIVE = re.compile(r"^immich-db-backup-.+\.sql\.gz\.tmp$")
READ_CHUNK_SIZE = 1024 * 1024


class BackupCheckError(Exception):
    """Raised when there is no recent, complete, readable backup."""


def _verify_gzip(path: Path) -> None:
    try:
        with gzip.open(path, "rb") as archive:
            while archive.read(READ_CHUNK_SIZE):
                pass
    except (OSError, EOFError) as exc:
        raise BackupCheckError(f"final archive is unreadable or corrupt: {path}: {exc}") from exc


def check_backup(directory: Path, max_age_seconds: int, stale_temp_seconds: int, now: float) -> Path:
    if not directory.is_dir():
        raise BackupCheckError(f"backup directory is unavailable: {directory}")

    try:
        files = list(directory.iterdir())
    except OSError as exc:
        raise BackupCheckError(f"cannot list backup directory {directory}: {exc}") from exc

    stale_temps: list[Path] = []
    for path in files:
        if TEMP_ARCHIVE.fullmatch(path.name):
            try:
                if now - path.stat().st_mtime > stale_temp_seconds:
                    stale_temps.append(path)
            except OSError as exc:
                raise BackupCheckError(f"cannot inspect temporary archive {path}: {exc}") from exc
    if stale_temps:
        names = ", ".join(str(path) for path in sorted(stale_temps))
        raise BackupCheckError(f"stale incomplete .tmp archive(s) found: {names}")

    archives = [path for path in files if FINAL_ARCHIVE.fullmatch(path.name)]
    if not archives:
        raise BackupCheckError(f"no completed .sql.gz archive found in {directory}; .tmp files do not count")

    try:
        newest = max(archives, key=lambda path: path.stat().st_mtime)
        age = now - newest.stat().st_mtime
    except OSError as exc:
        raise BackupCheckError(f"cannot inspect final archive in {directory}: {exc}") from exc
    if age < 0:
        raise BackupCheckError(f"final archive timestamp is in the future: {newest}")
    if age > max_age_seconds:
        raise BackupCheckError(
            f"latest completed archive is stale ({age / 3600:.1f}h old, limit {max_age_seconds / 3600:.1f}h): {newest}"
        )

    _verify_gzip(newest)
    return newest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/data/backups"))
    parser.add_argument("--max-age-hours", type=float, default=36)
    parser.add_argument("--stale-temp-minutes", type=float, default=90)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.stale_temp_minutes <= 0:
        parser.error("age limits must be positive")

    try:
        archive = check_backup(
            args.directory,
            int(args.max_age_hours * 3600),
            int(args.stale_temp_minutes * 60),
            time.time(),
        )
    except BackupCheckError as exc:
        print(f"Immich backup health check failed: {exc}", file=sys.stderr)
        return 1

    print(f"Immich backup health check passed: verified {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
