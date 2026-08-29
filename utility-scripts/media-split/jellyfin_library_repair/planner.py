"""Pure desired-state planning for Jellyfin virtual-folder locations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from .models import (
    ConfigurationError,
    DecisionAction,
    LibraryConfig,
    LibraryKind,
    PlanDecision,
    RepairConfig,
    VirtualFolderState,
    canonicalize_path,
    validate_absolute_path,
)


class PlanningError(ValueError):
    """Raised when current Jellyfin state cannot be safely matched."""


@dataclass(frozen=True)
class LibraryPlan:
    """Reconciliation decisions for one selected Jellyfin library."""

    library: LibraryConfig
    current_paths: tuple[str, ...]
    decisions: tuple[PlanDecision, ...]

    @property
    def add_paths(self) -> tuple[str, ...]:
        return tuple(
            decision.path
            for decision in self.decisions
            if decision.action is DecisionAction.ADD and decision.path is not None
        )

    @property
    def remove_paths(self) -> tuple[str, ...]:
        return tuple(
            decision.path
            for decision in self.decisions
            if decision.action is DecisionAction.REMOVE and decision.path is not None
        )

    @property
    def preserve_paths(self) -> tuple[str, ...]:
        return tuple(
            decision.path
            for decision in self.decisions
            if decision.action is DecisionAction.PRESERVE and decision.path is not None
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
    def scan_required(self) -> bool:
        return any(
            decision.action in {DecisionAction.ADD, DecisionAction.REMOVE}
            for decision in self.decisions
        )

    @property
    def scan_gate(self) -> PlanDecision:
        return next(
            decision
            for decision in self.decisions
            if decision.action is DecisionAction.SCAN_GATE
        )

    def to_dict(self) -> dict[str, Any]:
        actions = {
            "add": list(self.add_paths),
            "remove": list(self.remove_paths),
            "preserve": list(self.preserve_paths),
        }
        return {
            "library": self.library.to_public_dict(),
            "current_paths": list(self.current_paths),
            "actions": actions,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "scan_gate": self.scan_gate.to_dict(),
        }


@dataclass(frozen=True)
class ReconciliationPlan:
    """Complete deterministic plan, containing no resolved credential value."""

    config: RepairConfig
    libraries: tuple[LibraryPlan, ...]

    @property
    def decisions(self) -> tuple[PlanDecision, ...]:
        return tuple(decision for library in self.libraries for decision in library.decisions)

    @property
    def add_paths(self) -> tuple[str, ...]:
        return tuple(path for library in self.libraries for path in library.add_paths)

    @property
    def remove_paths(self) -> tuple[str, ...]:
        return tuple(path for library in self.libraries for path in library.remove_paths)

    @property
    def scan_required(self) -> bool:
        return any(library.scan_required for library in self.libraries)

    @property
    def plans(self) -> tuple[LibraryPlan, ...]:
        return self.libraries

    @property
    def scan_gate(self) -> dict[str, Any]:
        """The single batch-level scan gate for all selected libraries."""

        return {
            "action": "scan-gate",
            "required": self.scan_required,
            "reason": (
                "run exactly one controlled RefreshLibrary scan after all path mutations"
                if self.scan_required
                else "do not start a scan because no path mutation is required"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "jellyfin-library-repair-plan",
            "version": 1,
            "configuration": self.config.to_public_dict(),
            "libraries": [library.to_dict() for library in self.libraries],
            "scan_gate": self.scan_gate,
            "summary": {
                "add_count": len(self.add_paths),
                "remove_count": len(self.remove_paths),
                "scan_required": self.scan_required,
                "mode": "dry-run" if self.config.dry_run else "execute",
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _current_path_map(locations: Iterable[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for location in locations:
        exact = validate_absolute_path(location, "current path")
        normalized = canonicalize_path(exact, "current path")
        previous = paths.get(normalized)
        paths[normalized] = exact if previous is None else min(previous, exact)
    return paths


def _decision(
    library: LibraryConfig,
    action: DecisionAction,
    path: str | None,
    reason: str,
    explicit: bool = False,
) -> PlanDecision:
    return PlanDecision(
        library_kind=library.kind,
        library_name=library.name,
        action=action,
        path=path,
        explicit=explicit,
        reason=reason,
    )


def plan_library(
    library: LibraryConfig,
    current_locations: Iterable[str] | VirtualFolderState,
) -> LibraryPlan:
    """Plan one library without performing I/O or mutating its inputs.

    Existing locations are preserved unless they are listed explicitly in the
    matching obsolete-path list.  A scan gate is always emitted; it is marked
    required only when an add or explicit remove is present.
    """

    if isinstance(current_locations, VirtualFolderState):
        current_locations = current_locations.locations
    current_by_key = _current_path_map(current_locations)
    current_keys = set(current_by_key)
    desired = set(library.desired_paths)
    obsolete = set(library.obsolete_paths)

    decisions: list[PlanDecision] = []
    for path in sorted(desired - current_keys):
        decisions.append(
            _decision(library, DecisionAction.ADD, path, "desired path is not configured")
        )
    for key in sorted(current_keys.intersection(obsolete)):
        path = current_by_key[key]
        decisions.append(
            _decision(
                library,
                DecisionAction.REMOVE,
                path,
                "path is explicitly listed as obsolete",
                explicit=True,
            )
        )
    for key in sorted(current_keys - obsolete):
        path = current_by_key[key]
        reason = (
            "desired path is already configured"
            if key in desired
            else "unlisted existing root is preserved"
        )
        decisions.append(_decision(library, DecisionAction.PRESERVE, path, reason))

    has_mutation = any(
        decision.action in {DecisionAction.ADD, DecisionAction.REMOVE}
        for decision in decisions
    )
    gate_reason = (
        "run one controlled RefreshLibrary scan after path mutations"
        if has_mutation
        else "do not start a scan because no path mutation is required"
    )
    decisions.append(
        _decision(library, DecisionAction.SCAN_GATE, None, gate_reason)
    )
    current = tuple(current_by_key[key] for key in sorted(current_by_key))
    return LibraryPlan(library=library, current_paths=current, decisions=tuple(decisions))


def _as_virtual_folders(
    current_libraries: Iterable[VirtualFolderState | Mapping[str, Any]]
    | Mapping[str, Any],
) -> tuple[VirtualFolderState, ...]:
    if isinstance(current_libraries, Mapping):
        payload: Any = current_libraries
        if "Name" in payload or "name" in payload:
            current_libraries = (payload,)
        elif "virtual_folders" in payload:
            current_libraries = payload["virtual_folders"]
        elif "libraries" in payload:
            current_libraries = payload["libraries"]
        else:
            # A small mapping form is useful for local, read-only fixtures:
            # {"Movies": ["/media/movies/1"], "Series": ["/media/series/1"]}.
            current_libraries = tuple(
                {"name": name, "locations": locations}
                for name, locations in payload.items()
            )

    states: list[VirtualFolderState] = []
    for value in current_libraries:
        if isinstance(value, VirtualFolderState):
            states.append(value)
        elif isinstance(value, Mapping):
            states.append(VirtualFolderState.from_mapping(value))
        else:
            raise PlanningError("current virtual-folder entries must be objects")
    return tuple(states)


def _match_library(
    library: LibraryConfig,
    current_libraries: Sequence[VirtualFolderState],
) -> VirtualFolderState:
    candidates = [state for state in current_libraries if state.name == library.name]
    if not candidates:
        kind = LibraryKind.coerce(library.kind)
        raise PlanningError(
            f"selected {kind.value} library {library.name!r} was not found"
        )
    matching_type = [
        state
        for state in candidates
        if state.collection_type is None
        or state.collection_type == library.collection_type
    ]
    if not matching_type:
        actual = sorted(
            {state.collection_type or "<missing>" for state in candidates}
        )[0]
        raise PlanningError(
            f"library {library.name!r} has collection type {actual!r}; "
            f"expected {library.collection_type!r}"
        )
    if len(matching_type) > 1:
        raise PlanningError(f"current state contains duplicate library {library.name!r}")
    return matching_type[0]


def plan_reconciliation(
    config: RepairConfig,
    current_libraries: Iterable[VirtualFolderState | Mapping[str, Any]]
    | Mapping[str, Any],
) -> ReconciliationPlan:
    """Build a plan from a Jellyfin ``VirtualFolders`` response or fixture.

    The function is deliberately strict about selected library identity and
    collection type.  It performs no HTTP, subprocess, filesystem mutation, or
    credential lookup.
    """

    if not isinstance(config, RepairConfig):
        raise PlanningError("planner requires a validated RepairConfig")
    states = _as_virtual_folders(current_libraries)
    plans = tuple(
        plan_library(library, _match_library(library, states))
        for library in config.libraries
    )
    return ReconciliationPlan(config=config, libraries=plans)


def build_plan(
    config: RepairConfig,
    current_libraries: Iterable[VirtualFolderState | Mapping[str, Any]]
    | Mapping[str, Any],
) -> ReconciliationPlan:
    """Public descriptive alias for :func:`plan_reconciliation`."""

    return plan_reconciliation(config, current_libraries)


def serialize_plan(plan: ReconciliationPlan) -> str:
    """Serialize a plan using stable JSON ordering and no secret values."""

    if not isinstance(plan, ReconciliationPlan):
        raise ConfigurationError("serialize_plan requires a ReconciliationPlan")
    return plan.to_json()


# Clear aliases for callers that prefer an imperative name.
create_plan = plan_reconciliation
build_library_plan = plan_library
build_reconciliation_plan = plan_reconciliation
make_plan = plan_reconciliation
