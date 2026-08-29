"""Command-line parsing and read-only plan/configuration rendering.

This module intentionally creates no Jellyfin API client.  With
``--current-state`` it reads a local JSON fixture/GET capture and renders the
pure planner's result; without it, it renders only the validated configuration
for the later API orchestration subtask.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from .models import (
    ClusterSecretLookup,
    ConfigurationError,
    CredentialSource,
    LibraryConfig,
    LibraryKind,
    RepairConfig,
)
from .planner import PlanningError, plan_reconciliation


DEFAULT_API_KEY_ENV = "JELLYFIN_API_KEY"


class CliValidationError(ConfigurationError):
    """Raised by programmatic parsing before any orchestration is created."""


def build_parser() -> argparse.ArgumentParser:
    """Create the parser without reading environment values or doing I/O."""

    parser = argparse.ArgumentParser(
        prog="repair-jellyfin-libraries.sh",
        description=(
            "Validate explicit Jellyfin movie/series paths and print a "
            "read-only reconciliation plan. No API calls are made by this command."
        ),
    )
    parser.add_argument(
        "--base-url",
        "--url",
        "--jellyfin-url",
        required=True,
        help="Jellyfin server base URL, for example https://jellyfin.example",
    )
    parser.add_argument(
        "--movies-library",
        "--movies-library-name",
        "--movie-library",
        "--movie-library-name",
        dest="movies_library",
        help="name of the Jellyfin movie library",
    )
    parser.add_argument(
        "--series-library",
        "--series-library-name",
        dest="series_library",
        help="name of the Jellyfin series library",
    )
    parser.add_argument(
        "--movies-collection-type",
        "--movie-collection-type",
        "--movies-type",
        "--expected-movies-collection-type",
        dest="movies_collection_type",
        default="movies",
        help="expected collection type for the movie library (default: movies)",
    )
    parser.add_argument(
        "--series-collection-type",
        "--series-type",
        "--expected-series-collection-type",
        dest="series_collection_type",
        default="tvshows",
        help="expected collection type for the series library (default: tvshows)",
    )
    parser.add_argument(
        "--movies-path",
        "--movie-path",
        dest="movies_paths",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help="desired movie location; repeat for every numbered root",
    )
    parser.add_argument(
        "--series-path",
        dest="series_paths",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help="desired series location; repeat for every numbered root",
    )
    parser.add_argument(
        "--movies-obsolete-path",
        "--obsolete-movies-path",
        "--movie-obsolete-path",
        "--obsolete-movie-path",
        "--movies-obsolete",
        dest="movies_obsolete_paths",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help="explicit obsolete movie location to remove; repeat as needed",
    )
    parser.add_argument(
        "--series-obsolete-path",
        "--obsolete-series-path",
        "--series-obsolete",
        dest="series_obsolete_paths",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help="explicit obsolete series location to remove; repeat as needed",
    )
    parser.add_argument(
        "--obsolete-path",
        dest="global_obsolete_paths",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help=(
            "explicit obsolete location; applies to every selected library "
            "(prefer the scoped options when movie and series roots differ)"
        ),
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--api-key-env",
        "--token-env",
        "--credential-env",
        "--api-key-variable",
        dest="api_key_env",
        default=DEFAULT_API_KEY_ENV,
        metavar="VARIABLE",
        help=f"environment variable containing the API token (default: {DEFAULT_API_KEY_ENV})",
    )
    source.add_argument(
        "--from-cluster",
        action="store_true",
        help="use an explicitly named Kubernetes Secret as the future token source",
    )
    parser.add_argument(
        "--cluster-namespace",
        "--cluster-secret-namespace",
        default="media",
        metavar="NAMESPACE",
        help="namespace for --from-cluster (default: media)",
    )
    parser.add_argument(
        "--cluster-secret",
        "--cluster-secret-name",
        dest="cluster_secret_name",
        metavar="NAME",
        help="Secret name for --from-cluster",
    )
    parser.add_argument(
        "--cluster-key",
        "--cluster-secret-key",
        dest="cluster_secret_key",
        metavar="KEY",
        help="Secret data key for --from-cluster",
    )

    parser.add_argument(
        "--timeout",
        "--request-timeout",
        dest="request_timeout",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="future API request timeout (default: 60)",
    )
    parser.add_argument(
        "--poll-interval",
        "--scan-poll-interval",
        dest="poll_interval",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="future scan-task polling interval (default: 5)",
    )
    parser.add_argument(
        "--poll-timeout",
        "--scan-timeout",
        dest="scan_timeout",
        type=float,
        default=1800.0,
        metavar="SECONDS",
        help="future scan-task polling timeout (default: 1800)",
    )
    parser.add_argument(
        "--ca-file",
        "--tls-ca-file",
        "--tls-ca",
        dest="ca_file",
        metavar="PATH",
        help="CA bundle path for future HTTPS calls",
    )
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument(
        "--insecure",
        "--insecure-skip-tls-verify",
        dest="insecure",
        action="store_true",
        help="disable TLS certificate verification for a controlled future call",
    )

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run",
        dest="mode",
        action="store_const",
        const="dry-run",
        help="print the plan without applying changes (default)",
    )
    modes.add_argument(
        "--execute",
        dest="mode",
        action="store_const",
        const="execute",
        help="explicitly authorize later orchestration to apply changes",
    )
    parser.set_defaults(mode="dry-run", insecure=False)

    parser.add_argument(
        "--current-state",
        "--current-virtual-folders",
        dest="current_state",
        metavar="JSON_FILE",
        help=(
            "optional local JSON capture of GET /Library/VirtualFolders; "
            "reading it performs no network operation"
        ),
    )
    return parser


def _scoped_obsolete_paths(namespace: argparse.Namespace) -> tuple[list[str], list[str]]:
    movies = list(namespace.movies_obsolete_paths)
    series = list(namespace.series_obsolete_paths)
    selected = [
        kind
        for kind, name in (
            (LibraryKind.MOVIES, namespace.movies_library),
            (LibraryKind.SERIES, namespace.series_library),
        )
        if name
    ]
    for value in namespace.global_obsolete_paths:
        if value.startswith("movies:") or value.startswith("movies="):
            movies.append(value[7:])
        elif value.startswith("series:") or value.startswith("series="):
            series.append(value[7:])
        elif len(selected) == 1 and selected[0] is LibraryKind.MOVIES:
            movies.append(value)
        elif len(selected) == 1 and selected[0] is LibraryKind.SERIES:
            series.append(value)
        else:
            # A global request is explicit and is applied to both selected
            # libraries.  This keeps --obsolete-path useful while the scoped
            # flags remain available for unambiguous movie/series repairs.
            movies.append(value)
            series.append(value)
    return movies, series


def _library(
    kind: LibraryKind,
    name: str | None,
    collection_type: str,
    desired_paths: Sequence[str],
    obsolete_paths: Sequence[str],
) -> LibraryConfig | None:
    has_inputs = bool(desired_paths or obsolete_paths)
    if name is None:
        if has_inputs:
            raise CliValidationError(
                f"{kind.value} paths require --{kind.value}-library"
            )
        return None
    if not desired_paths:
        raise CliValidationError(
            f"{kind.value} library {name!r} must have at least one --{kind.value}-path"
        )
    return LibraryConfig(
        kind=kind,
        name=name,
        collection_type=collection_type,
        desired_paths=tuple(desired_paths),
        obsolete_paths=tuple(obsolete_paths),
    )


def _credential_source(namespace: argparse.Namespace) -> CredentialSource:
    if namespace.from_cluster:
        if not namespace.cluster_secret_name or not namespace.cluster_secret_key:
            raise CliValidationError(
                "--from-cluster requires --cluster-secret and --cluster-key"
            )
        return CredentialSource.from_cluster(
            ClusterSecretLookup(
                namespace=namespace.cluster_namespace,
                name=namespace.cluster_secret_name,
                key=namespace.cluster_secret_key,
            )
        )
    if namespace.cluster_secret_name or namespace.cluster_secret_key:
        raise CliValidationError(
            "cluster Secret options require --from-cluster"
        )
    return CredentialSource.from_environment(namespace.api_key_env)


def _config_from_namespace(namespace: argparse.Namespace) -> RepairConfig:
    movies_obsolete, series_obsolete = _scoped_obsolete_paths(namespace)
    movies = _library(
        LibraryKind.MOVIES,
        namespace.movies_library,
        namespace.movies_collection_type,
        namespace.movies_paths,
        movies_obsolete,
    )
    series = _library(
        LibraryKind.SERIES,
        namespace.series_library,
        namespace.series_collection_type,
        namespace.series_paths,
        series_obsolete,
    )
    return RepairConfig(
        base_url=namespace.base_url,
        movies=movies,
        series=series,
        credential_source=_credential_source(namespace),
        request_timeout_seconds=namespace.request_timeout,
        poll_interval_seconds=namespace.poll_interval,
        scan_timeout_seconds=namespace.scan_timeout,
        tls_ca_file=namespace.ca_file,
        insecure=namespace.insecure,
        dry_run=namespace.mode == "dry-run",
        execute=namespace.mode == "execute",
    )


@dataclass(frozen=True)
class ParsedCli:
    """Validated config plus an optional local current-state capture path."""

    config: RepairConfig
    current_state: str | None


def parse_cli(argv: Sequence[str] | None = None) -> ParsedCli:
    """Parse and validate all input before a future API client can be built."""

    parser = build_parser()
    namespace = parser.parse_args(argv)
    try:
        config = _config_from_namespace(namespace)
    except ConfigurationError as exc:
        raise CliValidationError(str(exc)) from exc
    return ParsedCli(config=config, current_state=namespace.current_state)


def parse_args(argv: Sequence[str] | None = None) -> RepairConfig:
    """Return only the validated configuration for programmatic callers."""

    return parse_cli(argv).config


# Descriptive aliases keep the parser convenient for callers without making
# argparse or any future API client a package-level side effect.
create_parser = build_parser
parse_config = parse_args
parse_configuration = parse_args


def _read_current_state(path: str) -> Any:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CliValidationError(f"unable to read current-state JSON: {exc}") from exc


def _configuration_output(config: RepairConfig) -> dict[str, Any]:
    return {
        "kind": "jellyfin-library-repair-configuration",
        "version": 1,
        "configuration": config.to_public_dict(),
        "plan": None,
        "message": (
            "No current virtual-folder state supplied; no API calls were made. "
            "Pass --current-state to render reconciliation decisions."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        parsed = parse_cli(argv)
        if parsed.current_state:
            plan = plan_reconciliation(
                parsed.config,
                _read_current_state(parsed.current_state),
            )
            output = plan.to_dict()
        else:
            output = _configuration_output(parsed.config)
    except (CliValidationError, PlanningError) as exc:
        parser.error(str(exc))
    sys.stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
