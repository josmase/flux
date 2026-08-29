"""Post-scan verification of Jellyfin library path configuration.

Reads library locations from the Jellyfin API and confirms:

* Every desired path is present in the library's configured locations.
* Every explicitly obsolete path is absent.
* Residual locations (neither desired nor obsolete) are reported for manual
  review but never acted upon.

This module never deletes media, never edits SQLite, and never invokes
fabricated endpoints.  Stale-record cleanup is left to Jellyfin's built-in
RefreshLibrary lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import (
    ConfigurationError,
    RepairConfig,
    VirtualFolderState,
    canonicalize_path,
)


class VerificationError(RuntimeError):
    """Raised when verification detects an unrecoverable state."""


@dataclass(frozen=True)
class LibraryVerification:
    """Verification outcome for one selected library."""

    library_name: str
    library_kind: str
    desired_paths_present: tuple[str, ...]
    desired_paths_missing: tuple[str, ...]
    obsolete_paths_absent: tuple[str, ...]
    obsolete_paths_still_present: tuple[str, ...]
    residual_paths: tuple[str, ...]

    @property
    def success(self) -> bool:
        """True when every desired path is present and no obsolete path remains."""
        return not self.desired_paths_missing and not self.obsolete_paths_still_present

    def to_dict(self) -> dict[str, Any]:
        return {
            "library_name": self.library_name,
            "library_kind": self.library_kind,
            "desired_paths_present": list(self.desired_paths_present),
            "desired_paths_missing": list(self.desired_paths_missing),
            "obsolete_paths_absent": list(self.obsolete_paths_absent),
            "obsolete_paths_still_present": list(self.obsolete_paths_still_present),
            "residual_paths": list(self.residual_paths),
            "success": self.success,
        }


@dataclass(frozen=True)
class VerificationResult:
    """Aggregated verification outcome for all selected libraries."""

    library_verifications: tuple[LibraryVerification, ...]
    success: bool

    @property
    def libraries_checked(self) -> int:
        return len(self.library_verifications)

    @property
    def desired_paths_present(self) -> tuple[str, ...]:
        return tuple(
            path
            for lib in self.library_verifications
            for path in lib.desired_paths_present
        )

    @property
    def desired_paths_missing(self) -> tuple[str, ...]:
        return tuple(
            path
            for lib in self.library_verifications
            for path in lib.desired_paths_missing
        )

    @property
    def obsolete_paths_absent(self) -> tuple[str, ...]:
        return tuple(
            path
            for lib in self.library_verifications
            for path in lib.obsolete_paths_absent
        )

    @property
    def obsolete_paths_still_present(self) -> tuple[str, ...]:
        return tuple(
            path
            for lib in self.library_verifications
            for path in lib.obsolete_paths_still_present
        )

    @property
    def residual_paths(self) -> tuple[str, ...]:
        """Paths that are neither desired nor obsolete — manual review only."""
        return tuple(
            path
            for lib in self.library_verifications
            for path in lib.residual_paths
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "libraries_checked": self.libraries_checked,
            "desired_paths_present": list(self.desired_paths_present),
            "desired_paths_missing": list(self.desired_paths_missing),
            "obsolete_paths_absent": list(self.obsolete_paths_absent),
            "obsolete_paths_still_present": list(self.obsolete_paths_still_present),
            "residual_paths": list(self.residual_paths),
            "library_details": [lib.to_dict() for lib in self.library_verifications],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _path_key(path: str) -> str:
    """Canonical path key for set comparisons."""
    return canonicalize_path(path, "path")


def _has_exact_path(locations: tuple[str, ...], target: str) -> str | None:
    """Return the exact location spelling that matches *target*, or ``None``."""
    target_key = _path_key(target)
    for location in locations:
        if _path_key(location) == target_key:
            return location
    return None


def _state_from_folders(
    folders: list[Mapping[str, Any]],
) -> tuple[VirtualFolderState, ...]:
    """Convert a ``GET /Library/VirtualFolders`` response into immutable states."""
    states: list[VirtualFolderState] = []
    for folder in folders:
        if isinstance(folder, VirtualFolderState):
            states.append(folder)
        elif isinstance(folder, Mapping):
            states.append(VirtualFolderState.from_mapping(folder))
        else:
            raise VerificationError(
                "virtual-folder response contains a non-object entry"
            )
    return tuple(states)


def _find_library_state(
    library_name: str,
    collection_type: str,
    states: tuple[VirtualFolderState, ...],
) -> VirtualFolderState:
    """Find the matching library state by name and collection type."""
    candidates = [
        state
        for state in states
        if state.name == library_name
        and (state.collection_type is None or state.collection_type == collection_type)
    ]
    if not candidates:
        raise VerificationError(
            f"library {library_name!r} (type={collection_type!r}) "
            "not found in current state"
        )
    if len(candidates) > 1:
        raise VerificationError(
            f"ambiguous library {library_name!r} in current state"
        )
    return candidates[0]


def _verify_library(
    library_config: Any,
    state: VirtualFolderState,
) -> LibraryVerification:
    """Verify one library's paths against current Jellyfin state."""
    locations = state.locations
    desired = library_config.desired_paths
    obsolete = library_config.obsolete_paths
    desired_keys = {_path_key(p) for p in desired}
    obsolete_keys = {_path_key(p) for p in obsolete}

    present: list[str] = []
    missing: list[str] = []
    for path in desired:
        match = _has_exact_path(locations, path)
        if match is not None:
            present.append(path)
        else:
            missing.append(path)

    absent: list[str] = []
    still_present: list[str] = []
    for path in obsolete:
        match = _has_exact_path(locations, path)
        if match is None:
            absent.append(path)
        else:
            still_present.append(path)

    # Residual: configured locations that are neither desired nor obsolete.
    # These are preserved unlisted roots or stale records that Jellyfin
    # should clean up through its normal RefreshLibrary lifecycle.
    residual: list[str] = []
    for location in locations:
        loc_key = _path_key(location)
        if loc_key not in desired_keys and loc_key not in obsolete_keys:
            residual.append(location)

    kind_value = (
        library_config.kind.value
        if hasattr(library_config.kind, "value")
        else str(library_config.kind)
    )

    return LibraryVerification(
        library_name=library_config.name,
        library_kind=kind_value,
        desired_paths_present=tuple(present),
        desired_paths_missing=tuple(missing),
        obsolete_paths_absent=tuple(absent),
        obsolete_paths_still_present=tuple(still_present),
        residual_paths=tuple(sorted(residual)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_paths(
    client: Any,
    config: RepairConfig,
) -> VerificationResult:
    """Re-read library locations and verify the post-repair state.

    *client* must expose ``get_virtual_folders()`` returning the
    ``GET /Library/VirtualFolders`` response.

    Returns a :class:`VerificationResult` whose :pyattr:`success` is
    ``True`` only when every desired path is present and every explicit
    obsolete path is absent.  Residual paths are reported for manual
    review but never acted upon.
    """
    if not isinstance(config, RepairConfig):
        raise ConfigurationError("verification requires a RepairConfig")

    libraries = config.libraries
    if not libraries:
        raise ConfigurationError("no libraries configured for verification")

    # Read current state from the API.
    method = getattr(client, "get_virtual_folders", None)
    if not callable(method):
        raise ConfigurationError("API client does not provide get_virtual_folders")
    raw_folders = method()
    if not isinstance(raw_folders, (list, tuple)):
        raise VerificationError("GET /Library/VirtualFolders did not return an array")
    states = _state_from_folders(list(raw_folders))

    verifications: list[LibraryVerification] = []
    for library_config in libraries:
        state = _find_library_state(
            library_config.name,
            library_config.collection_type,
            states,
        )
        verifications.append(_verify_library(library_config, state))

    overall_success = all(v.success for v in verifications)
    return VerificationResult(
        library_verifications=tuple(verifications),
        success=overall_success,
    )


# Descriptive alias for callers that use imperative naming.
verify_library_paths = verify_paths


__all__ = [
    "LibraryVerification",
    "VerificationError",
    "VerificationResult",
    "verify_library_paths",
    "verify_paths",
]
