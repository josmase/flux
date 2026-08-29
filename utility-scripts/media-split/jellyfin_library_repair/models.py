"""Immutable data models and boundary validation for Jellyfin path repair.

Only non-secret credential *references* are represented here.  An API key is
never accepted as a command-line value and is never loaded while parsing a
configuration or serializing a plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
import posixpath
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class ConfigurationError(ValueError):
    """Raised when a repair configuration is unsafe or incomplete."""


class LibraryKind(str, Enum):
    """The two Jellyfin library types handled by this utility."""

    MOVIES = "movies"
    SERIES = "series"

    @classmethod
    def coerce(cls, value: "LibraryKind | str") -> "LibraryKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ConfigurationError(
                f"unsupported library kind: {value!r}; expected movies or series"
            ) from exc


class DecisionAction(str, Enum):
    """Actions emitted by the pure reconciliation planner."""

    ADD = "add"
    REMOVE = "remove"
    PRESERVE = "preserve"
    SCAN_GATE = "scan-gate"

    @classmethod
    def coerce(cls, value: "DecisionAction | str") -> "DecisionAction":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ConfigurationError(f"unsupported plan action: {value!r}") from exc


_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ConfigurationError(f"{field_name} must not have surrounding whitespace")
    return value


def validate_absolute_path(value: str, field_name: str = "path") -> str:
    """Validate a Jellyfin POSIX path without changing its spelling."""

    value = _text(value, field_name)
    if "\x00" in value:
        raise ConfigurationError(f"{field_name} must not contain NUL characters")
    if not value.startswith("/"):
        raise ConfigurationError(f"{field_name} must be an absolute path")
    if ".." in value.split("/"):
        raise ConfigurationError(f"{field_name} must not contain '..' path components")
    return value


def canonicalize_path(value: str, field_name: str = "path") -> str:
    """Validate a Jellyfin POSIX path and return its stable representation.

    Jellyfin in this deployment sees NFS-backed POSIX paths.  Rejecting
    traversal components rather than silently resolving them keeps an explicit
    obsolete-path request from referring to a different location than the
    operator reviewed.
    """

    value = validate_absolute_path(value, field_name)

    normalized = posixpath.normpath(value)
    if not normalized.startswith("/"):
        raise ConfigurationError(f"{field_name} must be an absolute path")
    # posixpath deliberately preserves a double leading slash.  Treat it as
    # one root so duplicate desired paths cannot bypass validation.
    return "/" + normalized.lstrip("/") if normalized != "/" else "/"


def _paths(
    values: Iterable[str] | None,
    field_name: str,
    *,
    normalize: bool = True,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = (
            canonicalize_path(value, field_name)
            if normalize
            else validate_absolute_path(value, field_name)
        )
        if path in seen:
            raise ConfigurationError(f"duplicate {field_name}: {path}")
        seen.add(path)
        normalized.append(path)
    return tuple(normalized)


def _positive_number(value: float, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ConfigurationError(f"{field_name} must be a positive number")
    return number


@dataclass(frozen=True)
class PlanDecision:
    """One deterministic action for a library path or scan gate."""

    library_kind: LibraryKind | str
    library_name: str
    action: DecisionAction | str
    path: str | None
    explicit: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        kind = LibraryKind.coerce(self.library_kind)
        action = DecisionAction.coerce(self.action)
        name = _text(self.library_name, "plan library name")
        if self.path is not None:
            path = validate_absolute_path(self.path, "plan path")
        elif action is not DecisionAction.SCAN_GATE:
            raise ConfigurationError("only a scan-gate decision may omit a path")
        else:
            path = None
        object.__setattr__(self, "library_kind", kind)
        object.__setattr__(self, "library_name", name)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "path", path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_kind": LibraryKind.coerce(self.library_kind).value,
            "library_name": self.library_name,
            "action": DecisionAction.coerce(self.action).value,
            "path": self.path,
            "explicit": self.explicit,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LibraryConfig:
    """Desired configuration for one Jellyfin virtual folder."""

    kind: LibraryKind | str
    name: str
    collection_type: str
    desired_paths: tuple[str, ...] = ()
    obsolete_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        kind = LibraryKind.coerce(self.kind)
        name = _text(self.name, f"{kind.value} library name")
        collection_type = _text(
            self.collection_type, f"{kind.value} collection type"
        ).lower()
        desired = _paths(self.desired_paths, f"{kind.value} desired path")
        obsolete = _paths(self.obsolete_paths, f"{kind.value} obsolete path")
        if not desired:
            raise ConfigurationError(
                f"{kind.value} library {name!r} must declare at least one desired path"
            )
        overlap = sorted(set(desired).intersection(obsolete))
        if overlap:
            raise ConfigurationError(
                f"{kind.value} path cannot be both desired and obsolete: {overlap[0]}"
            )

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "collection_type", collection_type)
        object.__setattr__(self, "desired_paths", desired)
        object.__setattr__(self, "obsolete_paths", obsolete)

    @property
    def paths(self) -> tuple[str, ...]:
        """Compatibility alias for the desired locations."""

        return self.desired_paths

    def to_public_dict(self) -> dict[str, Any]:
        """Return JSON-safe desired state without any credential material."""

        return {
            "kind": LibraryKind.coerce(self.kind).value,
            "name": self.name,
            "collection_type": self.collection_type,
            "desired_paths": list(self.desired_paths),
            "obsolete_paths": list(self.obsolete_paths),
        }


@dataclass(frozen=True)
class ClusterSecretLookup:
    """Reference to a Kubernetes Secret; it does not contain the secret value."""

    namespace: str
    name: str
    key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _text(self.namespace, "cluster namespace"))
        object.__setattr__(self, "name", _text(self.name, "cluster secret name"))
        object.__setattr__(self, "key", _text(self.key, "cluster secret key"))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "namespace": self.namespace,
            "secret_name": self.name,
            "secret_key": self.key,
        }


@dataclass(frozen=True)
class CredentialSource:
    """A non-secret source declaration for the future Jellyfin API client."""

    environment_variable: str | None = None
    cluster_lookup: ClusterSecretLookup | None = None

    def __post_init__(self) -> None:
        has_environment = self.environment_variable is not None
        has_cluster = self.cluster_lookup is not None
        if has_environment == has_cluster:
            raise ConfigurationError(
                "choose exactly one credential source: environment or cluster Secret"
            )
        if has_environment:
            variable = _text(self.environment_variable, "credential environment variable")
            if not _ENVIRONMENT_VARIABLE.fullmatch(variable):
                raise ConfigurationError(
                    "credential environment variable must be a shell variable name"
                )
            object.__setattr__(self, "environment_variable", variable)
        elif not isinstance(self.cluster_lookup, ClusterSecretLookup):
            raise ConfigurationError("cluster credential source is invalid")

    @classmethod
    def from_environment(cls, variable: str = "JELLYFIN_API_KEY") -> "CredentialSource":
        return cls(environment_variable=variable)

    @classmethod
    def from_cluster(cls, lookup: ClusterSecretLookup) -> "CredentialSource":
        return cls(cluster_lookup=lookup)

    @property
    def kind(self) -> str:
        return "environment" if self.environment_variable else "cluster-secret"

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize only lookup metadata; never resolve or include a secret."""

        if self.environment_variable:
            return {
                "type": "environment",
                "environment_variable": self.environment_variable,
            }
        lookup = self.cluster_lookup
        if lookup is None:
            raise ConfigurationError("cluster credential source is invalid")
        return {"type": "cluster-secret", **lookup.to_public_dict()}


@dataclass(frozen=True)
class VirtualFolderState:
    """The API-returned subset needed by the pure planner."""

    name: str
    collection_type: str | None = None
    locations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "current library name"))
        if self.collection_type is not None:
            object.__setattr__(
                self,
                "collection_type",
                _text(self.collection_type, "current collection type").lower(),
            )
        # Preserve the exact spelling returned by Jellyfin.  The delete API
        # must receive the exact configured location; comparisons are
        # canonicalized by the planner separately.
        object.__setattr__(
            self,
            "locations",
            _paths(self.locations, "current path", normalize=False),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VirtualFolderState":
        """Read Jellyfin's PascalCase response or a snake_case test fixture."""

        if not isinstance(value, Mapping):
            raise ConfigurationError("current virtual folder must be an object")
        name = value.get("Name", value.get("name"))
        collection_type = value.get("CollectionType", value.get("collection_type"))
        locations = value.get("Locations", value.get("locations"))
        if locations is None:
            options = value.get("LibraryOptions", value.get("library_options", {})) or {}
            path_infos = options.get("PathInfos", options.get("path_infos", []))
            locations = [
                item.get("Path", item.get("path"))
                if isinstance(item, Mapping)
                else item
                for item in path_infos
            ]
        return cls(
            name=name,
            collection_type=collection_type,
            locations=tuple(locations or ()),
        )


@dataclass(frozen=True)
class RepairConfig:
    """Validated CLI configuration shared with later orchestration."""

    base_url: str
    movies: LibraryConfig | None = None
    series: LibraryConfig | None = None
    credential_source: CredentialSource = field(
        default_factory=CredentialSource.from_environment
    )
    request_timeout_seconds: float = 60.0
    poll_interval_seconds: float = 5.0
    scan_timeout_seconds: float = 1800.0
    tls_ca_file: str | None = None
    insecure: bool = False
    dry_run: bool = True
    execute: bool = False

    def __post_init__(self) -> None:
        raw_url = _text(self.base_url, "Jellyfin base URL")
        try:
            parsed = urlsplit(raw_url)
        except ValueError as exc:
            raise ConfigurationError("Jellyfin base URL is malformed") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError(
                "Jellyfin base URL must include an http:// or https:// host"
            )
        if parsed.username is not None or parsed.password is not None:
            raise ConfigurationError("Jellyfin base URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ConfigurationError("Jellyfin base URL must not contain a query or fragment")
        base_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )

        libraries = tuple(library for library in (self.movies, self.series) if library)
        if not libraries:
            raise ConfigurationError("at least one movie or series library is required")
        if self.movies is not None and not isinstance(self.movies, LibraryConfig):
            raise ConfigurationError("movies configuration is invalid")
        if self.series is not None and not isinstance(self.series, LibraryConfig):
            raise ConfigurationError("series configuration is invalid")
        if self.movies and self.movies.kind is not LibraryKind.MOVIES:
            raise ConfigurationError("movies configuration must use the movies library kind")
        if self.series and self.series.kind is not LibraryKind.SERIES:
            raise ConfigurationError("series configuration must use the series library kind")
        names = [library.name for library in libraries]
        if len(names) != len(set(names)):
            raise ConfigurationError("movie and series library names must be distinct")

        all_desired = [path for library in libraries for path in library.desired_paths]
        if len(all_desired) != len(set(all_desired)):
            raise ConfigurationError("desired paths must be unique across libraries")
        all_obsolete = [path for library in libraries for path in library.obsolete_paths]
        overlap = sorted(set(all_desired).intersection(all_obsolete))
        if overlap:
            raise ConfigurationError(
                f"path cannot be both desired and obsolete: {overlap[0]}"
            )

        if not isinstance(self.credential_source, CredentialSource):
            raise ConfigurationError("credential source is invalid")
        if self.tls_ca_file is not None:
            ca_file = _text(self.tls_ca_file, "TLS CA file")
        else:
            ca_file = None
        if self.insecure and ca_file:
            raise ConfigurationError("--insecure cannot be combined with a TLS CA file")
        if self.dry_run and self.execute:
            raise ConfigurationError("dry-run and execute modes cannot be combined")
        # Direct callers may select execute by setting dry_run=False.  The CLI
        # itself always supplies the explicit pair of mode values.
        execute = bool(self.execute or not self.dry_run)
        dry_run = not execute

        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "request_timeout_seconds", _positive_number(
            self.request_timeout_seconds, "request timeout"
        ))
        object.__setattr__(self, "poll_interval_seconds", _positive_number(
            self.poll_interval_seconds, "poll interval"
        ))
        object.__setattr__(self, "scan_timeout_seconds", _positive_number(
            self.scan_timeout_seconds, "scan timeout"
        ))
        object.__setattr__(self, "tls_ca_file", ca_file)
        object.__setattr__(self, "dry_run", dry_run)
        object.__setattr__(self, "execute", execute)

    @property
    def timeout_seconds(self) -> float:
        """Short alias used by future API orchestration."""

        return self.request_timeout_seconds

    @property
    def poll_interval(self) -> float:
        return self.poll_interval_seconds

    @property
    def poll_timeout_seconds(self) -> float:
        return self.scan_timeout_seconds

    @property
    def ca_file(self) -> str | None:
        return self.tls_ca_file

    @property
    def mode(self) -> str:
        return "dry-run" if self.dry_run else "execute"

    @property
    def is_dry_run(self) -> bool:
        return self.dry_run

    @property
    def movies_library(self) -> LibraryConfig | None:
        return self.movies

    @property
    def series_library(self) -> LibraryConfig | None:
        return self.series

    @property
    def libraries(self) -> tuple[LibraryConfig, ...]:
        return tuple(library for library in (self.movies, self.series) if library)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize configuration without reading or including credentials."""

        return {
            "base_url": self.base_url,
            "libraries": [library.to_public_dict() for library in self.libraries],
            "credential_source": self.credential_source.to_public_dict(),
            "request_timeout_seconds": self.request_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "scan_timeout_seconds": self.scan_timeout_seconds,
            "tls_ca_file": self.tls_ca_file,
            "insecure": self.insecure,
            "mode": self.mode,
        }


# Descriptive aliases for integrations that use "configuration" or "spec"
# terminology; the immutable implementations above remain the canonical API.
LibrarySpec = LibraryConfig
CurrentLibrary = VirtualFolderState
CurrentVirtualFolder = VirtualFolderState
RepairConfiguration = RepairConfig
PlanAction = DecisionAction
