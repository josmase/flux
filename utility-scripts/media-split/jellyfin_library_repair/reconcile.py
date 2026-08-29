"""Safely apply a Jellyfin library-path reconciliation plan.

This module intentionally stops after path configuration.  It does not start a
library refresh or inspect scheduled tasks; a later orchestration step can use
the returned ``scan_required`` signal after this operation has completed.

The API client owns the v10.11.9 HTTP details, including the fixed
``refreshLibrary=false`` query parameter and the no-retry mutation policy.  The
reconciler owns the ordering and verification policy:

* read and strictly identify every selected library before mutating;
* add missing locations and verify the complete desired set before removing;
* remove only exact locations selected by the pure planner; and
* verify every deletion before attempting the next one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol
from dataclasses import dataclass
from typing import Any, cast

from .models import (
    ConfigurationError,
    RepairConfig,
    VirtualFolderState,
    canonicalize_path,
)
from .planner import (
    LibraryPlan,
    PlanningError,
    ReconciliationPlan,
    plan_reconciliation,
)


class LibraryPathClient(Protocol):
    """The small API-client surface required by this module."""

    def get_virtual_folders(self) -> list[Mapping[str, Any]]:
        """Return the current ``GET /Library/VirtualFolders`` response."""

    def add_virtual_folder_path(self, library_name: str, path: str) -> Any:
        """Add one location using the client's safe path endpoint."""

    def remove_virtual_folder_path(self, library_name: str, path: str) -> Any:
        """Remove one location using the client's safe path endpoint."""


class ReconciliationError(RuntimeError):
    """Raised when current state cannot be safely reconciled."""


class PathReadinessError(ReconciliationError):
    """Raised when Jellyfin does not expose every desired path after an add."""


class PathVerificationError(ReconciliationError):
    """Raised when a successful-looking deletion is not reflected by a read."""


class MutationResponseError(ReconciliationError):
    """Raised when an injected client does not report the documented status."""

    def __init__(
        self,
        operation: str,
        library_name: str,
        path: str,
        status: int | None,
    ) -> None:
        self.operation = operation
        self.library_name = library_name
        self.path = path
        self.status = status
        status_text = "unknown" if status is None else str(status)
        super().__init__(
            f"{operation} of {path!r} in library {library_name!r} "
            f"did not report HTTP 204 (status {status_text})"
        )


@dataclass(frozen=True)
class ReconciliationResult:
    """The non-secret result of the path phase.

    ``plan`` is the pre-mutation plan, so a caller can see the complete
    add/remove/preserve decision that authorized the operation.  ``final_plan``
    is the last verified read.  Neither field contains credentials.
    """

    plan: ReconciliationPlan
    final_plan: ReconciliationPlan
    added_paths: tuple[str, ...] = ()
    removed_paths: tuple[str, ...] = ()
    dry_run: bool = True

    @property
    def executed(self) -> bool:
        """Whether this result came from the mutation path."""

        return not self.dry_run

    @property
    def mutated(self) -> bool:
        """Whether this invocation successfully applied at least one change."""

        return bool(self.added_paths or self.removed_paths)

    @property
    def scan_required(self) -> bool:
        """Whether a later orchestration step should consider one scan."""

        return self.plan.scan_required

    @property
    def add_paths(self) -> tuple[str, ...]:
        """Compatibility view of the plan's additions."""

        return self.plan.add_paths

    @property
    def remove_paths(self) -> tuple[str, ...]:
        """Compatibility view of the plan's removals."""

        return self.plan.remove_paths

    @property
    def preserve_paths(self) -> tuple[str, ...]:
        """The roots preserved by the original plan."""

        return tuple(
            path
            for library in self.plan.libraries
            for path in library.preserve_paths
        )

    @property
    def additions(self) -> tuple[str, ...]:
        return self.add_paths

    @property
    def removals(self) -> tuple[str, ...]:
        return self.remove_paths

    @property
    def preserved(self) -> tuple[str, ...]:
        return self.preserve_paths

    @property
    def libraries(self) -> tuple[LibraryPlan, ...]:
        """Expose the plan shape for callers that do not need execution data."""

        return self.plan.libraries

    @property
    def decisions(self) -> tuple[Any, ...]:
        return self.plan.decisions

    def to_dict(self) -> dict[str, Any]:
        """Serialize the plan and verified path-phase outcome."""

        output = self.plan.to_dict()
        output["execution"] = {
            "mode": "dry-run" if self.dry_run else "execute",
            "added": list(self.added_paths),
            "removed": list(self.removed_paths),
            "final_plan": self.final_plan.to_dict(),
            "scan_required": self.scan_required,
        }
        return output


def _state_values(
    current_libraries: Iterable[VirtualFolderState | Mapping[str, Any]]
    | Mapping[str, Any]
    | VirtualFolderState,
) -> tuple[VirtualFolderState, ...]:
    """Convert supported GET/test payload forms into immutable states."""

    if isinstance(current_libraries, VirtualFolderState):
        values: Iterable[VirtualFolderState | Mapping[str, Any]] = (current_libraries,)
    elif isinstance(current_libraries, Mapping):
        if "Name" in current_libraries or "name" in current_libraries:
            values = (current_libraries,)
        elif "virtual_folders" in current_libraries:
            values = cast(Iterable[VirtualFolderState | Mapping[str, Any]], current_libraries[
                "virtual_folders"
            ])
        elif "libraries" in current_libraries:
            values = cast(Iterable[VirtualFolderState | Mapping[str, Any]], current_libraries[
                "libraries"
            ])
        else:
            # Keep the planner's convenient fixture form while still applying
            # strict identity checks below.
            values = tuple(
                {"name": name, "locations": locations}
                for name, locations in current_libraries.items()
            )
    else:
        values = current_libraries

    if isinstance(values, (str, bytes)):
        raise PlanningError("current virtual-folder response must be an object array")

    states: list[VirtualFolderState] = []
    try:
        for value in values:
            if isinstance(value, VirtualFolderState):
                states.append(value)
            elif isinstance(value, Mapping):
                states.append(VirtualFolderState.from_mapping(value))
            else:
                raise PlanningError("current virtual-folder entries must be objects")
    except TypeError as exc:
        raise PlanningError("current virtual-folder response must be iterable") from exc
    return tuple(states)


def _strict_plan(
    config: RepairConfig,
    current_libraries: Iterable[VirtualFolderState | Mapping[str, Any]]
    | Mapping[str, Any]
    | VirtualFolderState,
) -> ReconciliationPlan:
    """Build a plan only after strict name/type and path checks."""

    states = _state_values(current_libraries)
    for library in config.libraries:
        candidates = [state for state in states if state.name == library.name]
        if not candidates:
            raise PlanningError(
                f"selected {library.kind.value} library {library.name!r} was not found"
            )
        if len(candidates) != 1:
            raise PlanningError(
                f"current state contains ambiguous library {library.name!r}"
            )
        state = candidates[0]
        actual_type = state.collection_type or "<missing>"
        if actual_type != library.collection_type:
            raise PlanningError(
                f"library {library.name!r} has collection type {actual_type!r}; "
                f"expected {library.collection_type!r}"
            )

        # Two spellings that canonicalize to one location would make a
        # deletion target ambiguous.  Refuse to select one arbitrarily.
        normalized_paths = [canonicalize_path(path, "current path") for path in state.locations]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise PlanningError(
                f"library {library.name!r} contains duplicate configured locations"
            )

    return plan_reconciliation(config, states)


def _read(client: Any) -> tuple[VirtualFolderState, ...]:
    """Perform one fresh, read-only virtual-folder request."""

    method = getattr(client, "get_virtual_folders", None)
    if not callable(method):
        raise ConfigurationError("API client does not provide get_virtual_folders")
    return _state_values(method())


def _path_key(path: str) -> str:
    return canonicalize_path(path, "path")


def _has_path(paths: Iterable[str], target: str) -> bool:
    target_key = _path_key(target)
    return any(_path_key(path) == target_key for path in paths)


def _library_plan(plan: ReconciliationPlan, library_name: str) -> LibraryPlan:
    for library in plan.libraries:
        if library.library.name == library_name:
            return library
    raise PathVerificationError(f"library {library_name!r} disappeared during reconciliation")


def _ensure_desired_paths(plan: ReconciliationPlan, phase: str) -> None:
    """Require every desired location to be visible in the selected state."""

    missing: list[str] = []
    for library in plan.libraries:
        for desired in library.library.desired_paths:
            if not _has_path(library.current_paths, desired):
                missing.append(f"{library.library.name}: {desired}")
    if missing:
        raise PathReadinessError(
            f"{phase} Jellyfin state is missing desired paths: {', '.join(missing)}"
        )


def _status(value: Any) -> int | None:
    """Extract an optional status from common injectable-client responses."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (tuple, list)) and value:
        candidate = value[0]
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    if isinstance(value, Mapping):
        candidate = value.get("status", value.get("status_code"))
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    for attribute in ("status", "status_code"):
        candidate = getattr(value, attribute, None)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _exception_status(error: BaseException) -> int | None:
    """Read a status without depending on one concrete HTTP exception class."""

    for attribute in ("status", "status_code", "code"):
        candidate = getattr(error, attribute, None)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _require_success(
    operation: str,
    library_name: str,
    path: str,
    response: Any,
) -> None:
    """Trust only the client's checked 204 response (or an explicit 204 fake)."""

    if response is False:
        raise MutationResponseError(operation, library_name, path, None)
    response_status = _status(response)
    if response_status is not None and response_status != 204:
        raise MutationResponseError(operation, library_name, path, response_status)
    # JellyfinApiClient returns None after checking its 204 response.  A test
    # double may return None, True, or an explicit 204; no other status is
    # accepted above.


def _mutation_method(client: Any, operation: str) -> Any:
    names = {
        "add": ("add_virtual_folder_path", "add_library_path", "add_path"),
        "remove": ("remove_virtual_folder_path", "remove_library_path", "remove_path"),
    }[operation]
    for name in names:
        method = getattr(client, name, None)
        if callable(method):
            return method
    raise ConfigurationError(f"API client does not provide a safe {operation} path method")


def _add(client: Any, library_name: str, path: str) -> None:
    method = _mutation_method(client, "add")
    response = method(library_name, path)
    _require_success("add", library_name, path, response)


def _remove(
    client: Any,
    config: RepairConfig,
    library_name: str,
    path: str,
) -> tuple[ReconciliationPlan, bool]:
    """Remove once, then verify absence; a 404 gets one read-only check."""

    method = _mutation_method(client, "remove")
    try:
        response = method(library_name, path)
        _require_success("remove", library_name, path, response)
    except Exception as error:
        if _exception_status(error) != 404 and _status(error) != 404:
            raise
        # A 404 is not success by itself.  It is acceptable only if the exact
        # configured location is absent in a fresh, strictly matched response.
        verified_plan = _strict_plan(config, _read(client))
        current_library = _library_plan(verified_plan, library_name)
        if _has_path(current_library.current_paths, path):
            raise
        return verified_plan, True

    verified_plan = _strict_plan(config, _read(client))
    current_library = _library_plan(verified_plan, library_name)
    if _has_path(current_library.current_paths, path):
        raise PathVerificationError(
            f"Jellyfin still reports {path!r} in library {library_name!r} after removal"
        )
    return verified_plan, True


def _removal_requests(plan: ReconciliationPlan) -> tuple[tuple[str, str], ...]:
    return tuple(
        (library.library.name, path)
        for library in plan.libraries
        for path in library.remove_paths
    )


def reconcile(
    client: LibraryPathClient | Any,
    config: RepairConfig | ReconciliationPlan,
    *,
    execute: bool | None = None,
) -> ReconciliationResult:
    """Re-read and safely reconcile selected Jellyfin library locations.

    The canonical call is ``reconcile(client, config)``.  Passing a plan is
    supported for callers that already rendered a dry-run plan, but the plan is
    never trusted as current state: this function always performs a fresh GET.
    ``execute`` is an optional programmatic override; the CLI/configuration
    remains dry-run by default.

    No scheduled task or scan endpoint is called here.
    """

    if isinstance(client, RepairConfig) and isinstance(config, (RepairConfig, ReconciliationPlan)):
        # Permit the descriptive ``reconcile(config, client)`` spelling without
        # weakening the canonical, explicitly typed form.
        client, config = config, cast(Any, client)
    if isinstance(config, ReconciliationPlan):
        repair_config = config.config
    elif isinstance(config, RepairConfig):
        repair_config = config
    else:
        raise ConfigurationError("reconciler requires a validated RepairConfig or plan")

    requested_execute = repair_config.execute if execute is None else bool(execute)
    initial_plan = _strict_plan(repair_config, _read(client))
    if not requested_execute:
        return ReconciliationResult(
            plan=initial_plan,
            final_plan=initial_plan,
            dry_run=True,
        )

    added: list[str] = []
    removed: list[str] = []
    working_plan = initial_plan

    # Add every missing desired path before considering any removal.  A failed
    # or unavailable add propagates immediately, so no removal follows it.
    if initial_plan.add_paths:
        for library in initial_plan.libraries:
            for path in library.add_paths:
                _add(client, library.library.name, path)
                added.append(path)

        working_plan = _strict_plan(repair_config, _read(client))
        _ensure_desired_paths(working_plan, "post-add")
        if working_plan.add_paths:
            raise PathReadinessError(
                "post-add Jellyfin state still requires desired path additions"
            )
    elif initial_plan.remove_paths:
        # Re-read before a removal as well, so the DELETE target is the exact
        # location returned by the latest Jellyfin state.
        working_plan = _strict_plan(repair_config, _read(client))
        _ensure_desired_paths(working_plan, "pre-remove")

    # The planner emits only explicitly obsolete removals.  Every individual
    # DELETE is followed by a fresh read before the next DELETE is attempted.
    for library_name, path in _removal_requests(working_plan):
        working_plan, was_removed = _remove(
            client,
            repair_config,
            library_name,
            path,
        )
        if was_removed:
            removed.append(path)

    return ReconciliationResult(
        plan=initial_plan,
        final_plan=working_plan,
        added_paths=tuple(added),
        removed_paths=tuple(removed),
        dry_run=False,
    )


def reconcile_paths(
    client: LibraryPathClient | Any,
    config: RepairConfig | ReconciliationPlan,
    *,
    execute: bool | None = None,
) -> ReconciliationResult:
    """Descriptive alias for :func:`reconcile`."""

    return reconcile(client, config, execute=execute)


def reconcile_library_paths(
    client: LibraryPathClient | Any,
    config: RepairConfig | ReconciliationPlan,
    *,
    execute: bool | None = None,
) -> ReconciliationResult:
    """Descriptive alias for :func:`reconcile`."""

    return reconcile(client, config, execute=execute)


apply_reconciliation = reconcile
apply_plan = reconcile


__all__ = [
    "LibraryPathClient",
    "MutationResponseError",
    "PathReadinessError",
    "PathVerificationError",
    "ReconciliationError",
    "ReconciliationResult",
    "apply_plan",
    "apply_reconciliation",
    "reconcile",
    "reconcile_library_paths",
    "reconcile_paths",
]
