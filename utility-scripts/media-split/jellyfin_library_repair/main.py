"""Orchestration entrypoint for the Jellyfin library path repair utility.

Validates all requested libraries and desired paths before the first mutation,
supports movie-only, series-only, and combined runs, and returns nonzero on
any failed operation.

Workflow
--------
1. Parse and validate CLI arguments.
2. ``--dry-run`` (default): authenticated reads only, prints counts, exact
   planned adds / removes / preserved roots, and the scan gate.
3. ``--execute``: path reconciliation with ``refreshLibrary=false``, at most
   one polled ``RefreshLibrary`` scan when a mutation occurred, then
   verification.

The scan lock is acquired and released by :class:`RefreshLibraryScanner`.
Successful path mutations are never automatically rolled back; the exact
state and rollback instructions are reported instead.  Stale-record cleanup
is left to Jellyfin's built-in lifecycle — no fabricated ``CleanDatabase``
endpoint is ever invoked.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

from .api import JellyfinApiClient
from .cli import CliValidationError, build_parser, parse_cli
from .credentials import CredentialError
from .models import ConfigurationError, RepairConfig
from .planner import PlanningError, plan_reconciliation
from .reconcile import ReconciliationError, reconcile
from .scanner import ScanError, ScanOutcome, RefreshLibraryScanner
from .verify import VerificationError, verify_paths


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_json(data: dict[str, Any]) -> None:
    """Write pretty-printed JSON to stdout."""
    sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _print_error(message: str) -> None:
    """Write an error message to stderr."""
    sys.stderr.write(f"Error: {message}\n")


def _scan_summary(outcome: ScanOutcome) -> dict[str, Any]:
    """Produce a JSON-safe summary of a scan outcome."""
    summary: dict[str, Any] = {
        "success": outcome.success,
        "started": outcome.started,
        "polls": outcome.polls,
    }
    if outcome.task_id is not None:
        summary["task_id"] = outcome.task_id
    if outcome.status is not None:
        summary["status"] = outcome.status
    if outcome.error_message is not None:
        summary["error"] = outcome.error_message
    return summary


# ---------------------------------------------------------------------------
# Mode handlers
# ---------------------------------------------------------------------------


def _offline_plan(config: RepairConfig, current_state_path: str) -> int:
    """Render a reconciliation plan from a local JSON capture (no API calls)."""
    from pathlib import Path

    try:
        raw = json.loads(Path(current_state_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _print_error(f"unable to read current-state JSON: {exc}")
        return 1

    try:
        plan = plan_reconciliation(config, raw)
    except (ConfigurationError, PlanningError) as exc:
        _print_error(str(exc))
        return 1

    _print_json(plan.to_dict())
    return 0


def _dry_run(client: Any, config: RepairConfig) -> int:
    """Authenticated reads only — no POST, DELETE, task start, or scan."""
    try:
        result = reconcile(client, config)
    except (ConfigurationError, PlanningError, ReconciliationError) as exc:
        _print_error(f"reconciliation plan failed: {exc}")
        return 1

    _print_json(result.to_dict())
    return 0


def _execute(client: Any, config: RepairConfig) -> int:
    """Apply path reconciliation, one scan if mutated, then verification."""
    # Phase 1 — path reconciliation (validates before the first mutation).
    try:
        result = reconcile(client, config, execute=True)
    except ReconciliationError as exc:
        _print_error(f"path reconciliation failed: {exc}")
        _print_error(
            "Some path mutations may have been applied. Run with --dry-run to "
            "inspect the current state, or check GET /Library/VirtualFolders "
            "manually. Do not retry mutations without verifying current locations."
        )
        return 1
    except Exception as exc:
        _print_error(f"unexpected error during path reconciliation: {exc}")
        _print_error(
            "Some path mutations may have been applied. Run with --dry-run to "
            "inspect the current state."
        )
        return 1

    # Phase 2 — at most one polled RefreshLibrary scan when mutation occurred.
    # The scanner acquires and releases the inter-process lock for the full
    # discover / start / poll lifecycle; the lock is released automatically on
    # success, failure, timeout, or interruption.
    scan_outcome: ScanOutcome | None = None
    if result.mutated:
        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=config.scan_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
        )
        try:
            scan_outcome = scanner.scan()
        except ScanError as exc:
            scan_outcome = exc.outcome
            _print_error(
                f"RefreshLibrary scan failed: {exc}. Path mutations were applied "
                "but a manual scan may be needed."
            )

    # Phase 3 — post-scan / post-no-op verification.
    try:
        verification = verify_paths(client, config)
    except (VerificationError, ConfigurationError) as exc:
        _print_error(f"verification failed: {exc}")
        output: dict[str, Any] = {
            "reconciliation": result.to_dict(),
            "scan": (
                _scan_summary(scan_outcome) if scan_outcome is not None else None
            ),
            "verification_error": str(exc),
        }
        _print_json(output)
        return 1

    output = {
        "reconciliation": result.to_dict(),
        "scan": _scan_summary(scan_outcome) if scan_outcome is not None else None,
        "verification": verification.to_dict(),
    }
    _print_json(output)

    # Return nonzero on any failed operation.
    if not verification.success:
        return 1
    if scan_outcome is not None and not scan_outcome.success:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: validate, reconcile, optionally scan, then verify.

    Supports movie-only, series-only, and combined runs.  Dry-run is the
    default; execute mode requires the explicit ``--execute`` flag.
    """
    parser = build_parser()
    try:
        parsed = parse_cli(argv)
    except CliValidationError as exc:
        _print_error(str(exc))
        parser.print_help(sys.stderr)
        return 1

    # Offline plan rendering when a local state capture is provided.
    if parsed.current_state:
        return _offline_plan(parsed.config, parsed.current_state)

    # Build the authenticated API client (resolves credentials from the
    # configured source — never logs or prints the token).
    try:
        client = JellyfinApiClient.from_config(parsed.config)
    except CredentialError as exc:
        _print_error(str(exc))
        return 1
    except Exception as exc:
        _print_error(f"unable to build API client: {exc}")
        return 1

    if parsed.config.dry_run:
        return _dry_run(client, parsed.config)

    return _execute(client, parsed.config)


__all__ = [
    "main",
]
