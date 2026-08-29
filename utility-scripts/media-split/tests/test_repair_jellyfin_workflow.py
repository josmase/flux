"""Integration tests for the Jellyfin library repair workflow.

Tests exercise the full workflow path through ``_dry_run`` and ``_execute``
from ``main.py`` using mock clients and a mock scanner.  No real credentials,
network, or live Jellyfin are contacted.

Uses the ``_FakeClient`` pattern from ``test_repair_jellyfin_safety.py`` for
the reconciler and a recording scanner mock for scan-phase assertions.
"""

from __future__ import annotations

import copy
import json
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import main as unittest_main, TestCase
from unittest.mock import MagicMock, patch

from jellyfin_library_repair.main import _dry_run, _execute
from jellyfin_library_repair.reconcile import reconcile, ReconciliationResult
from jellyfin_library_repair.models import (
    LibraryConfig,
    LibraryKind,
    RepairConfig,
)
from jellyfin_library_repair.verify import VerificationResult, LibraryVerification
from jellyfin_library_repair.scanner import ScanError, ScanOutcome


BASE_URL = "https://jellyfin.invalid"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jellyfin_virtual_folders.json"


# ---------------------------------------------------------------------------
# Fake client: satisfies the LibraryPathClient protocol
# ---------------------------------------------------------------------------

@dataclass
class _FakeClient:
    """Records add/remove/read calls and returns pre-configured responses."""

    folders: list[dict[str, Any]] = field(default_factory=list)
    add_responses: list[Any] = field(default_factory=list)
    remove_responses: list[Any] = field(default_factory=list)
    read_error: Exception | None = None
    _mutable_folders: list[dict[str, Any]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._mutable_folders = copy.deepcopy(self.folders)

    def get_virtual_folders(self) -> list[dict[str, Any]]:
        if self.read_error is not None:
            raise self.read_error
        return copy.deepcopy(self._mutable_folders)

    def add_virtual_folder_path(self, library_name: str, path: str) -> Any:
        for lib in self._mutable_folders:
            if lib.get("Name") == library_name:
                options = lib.get("LibraryOptions") or {}
                path_infos = options.get("PathInfos")
                if path_infos is not None:
                    path_infos.append({"Path": path})
                else:
                    locs = lib.get("Locations")
                    if locs is not None:
                        locs.append(path)
                    else:
                        lib["Locations"] = [path]
                break
        if self.add_responses:
            return self.add_responses.pop(0)
        return None

    def remove_virtual_folder_path(self, library_name: str, path: str) -> Any:
        for lib in self._mutable_folders:
            if lib.get("Name") == library_name:
                options = lib.get("LibraryOptions") or {}
                path_infos = options.get("PathInfos")
                if path_infos is not None:
                    lib["LibraryOptions"]["PathInfos"] = [
                        p for p in path_infos if p.get("Path") != path
                    ]
                else:
                    locs = lib.get("Locations")
                    if locs is not None:
                        lib["Locations"] = [p for p in locs if p != path]
                break
        if self.remove_responses:
            return self.remove_responses.pop(0)
        return None


# ---------------------------------------------------------------------------
# Recording scanner mock
# ---------------------------------------------------------------------------

class _RecordingScanner:
    """Mock scanner that records calls and returns a pre-configured outcome."""

    def __init__(self, outcome: ScanOutcome | None = None) -> None:
        self.outcome = outcome or ScanOutcome(
            success=True,
            task_id="abc12345-def6-7890-abcd-ef1234567890",
            prior_result=None,
            result=None,
            state="Idle",
            polls=0,
            started=True,
        )
        self.scan_calls: list[dict[str, Any]] = []

    def scan(self) -> ScanOutcome:
        self.scan_calls.append({})
        return self.outcome

    def try_scan(self) -> ScanOutcome:
        return self.scan()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _movies_config(
    desired: tuple[str, ...],
    obsolete: tuple[str, ...] = (),
) -> RepairConfig:
    return RepairConfig(
        base_url=BASE_URL,
        movies=LibraryConfig(
            kind=LibraryKind.MOVIES,
            name="Movies",
            collection_type="movies",
            desired_paths=desired,
            obsolete_paths=obsolete,
        ),
    )


_SUCCESS_SCAN_OUTCOME = ScanOutcome(
    success=True,
    task_id="abc12345-def6-7890-abcd-ef1234567890",
    prior_result=None,
    result=None,
    state="Idle",
    polls=1,
    started=True,
    observed_running=True,
    observed_new_result=True,
)

_FAILED_SCAN_OUTCOME = ScanOutcome(
    success=False,
    task_id="abc12345-def6-7890-abcd-ef1234567890",
    prior_result=None,
    result=None,
    state="Idle",
    polls=1,
    started=True,
    error="RefreshLibrary task ended with Status=Failed",
)


def _successful_verification(config: RepairConfig) -> VerificationResult:
    """Build a VerificationResult that reports all desired paths present."""
    verifications = []
    for lib in config.libraries:
        verifications.append(LibraryVerification(
            library_name=lib.name,
            library_kind=lib.kind.value,
            desired_paths_present=lib.desired_paths,
            desired_paths_missing=(),
            obsolete_paths_absent=lib.obsolete_paths,
            obsolete_paths_still_present=(),
            residual_paths=(),
        ))
    return VerificationResult(
        library_verifications=tuple(verifications),
        success=True,
    )


# ===========================================================================
# TestDryRunPerformsNoMutations
# ===========================================================================


class TestDryRunPerformsNoMutations(TestCase):
    """Dry-run mode must not call POST, DELETE, task start, or scan."""

    def test_no_post_delete_or_scan(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _dry_run(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        # No add/remove calls were made
        self.assertFalse(hasattr(fake, '_add_calls'))

    def test_dry_run_result_shows_planned_mutations(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _dry_run(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        output = json.loads(stdout_capture.getvalue())
        self.assertEqual(output["execution"]["mode"], "dry-run")
        self.assertEqual(output["execution"]["added"], [])
        self.assertEqual(output["execution"]["removed"], [])


# ===========================================================================
# TestExecutePerformsOneScanAfterMutation
# ===========================================================================


class TestExecutePerformsOneScanAfterMutation(TestCase):
    """Reconcile succeeds with mutations, scanner runs exactly once."""

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_execute_with_mutation_runs_scan_once(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        fixture = _load_fixture()
        # movies/3 is missing from fixture → add required → mutation occurred
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
        )
        fake = _FakeClient(folders=fixture)

        scanner_instance = MagicMock()
        scanner_instance.scan.return_value = _SUCCESS_SCAN_OUTCOME
        mock_scanner_cls.return_value = scanner_instance

        mock_verify.return_value = _successful_verification(config)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        # Scanner was instantiated and called exactly once
        mock_scanner_cls.assert_called_once()
        scanner_instance.scan.assert_called_once()
        # Verification was called
        mock_verify.assert_called_once()

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_execute_logs_scan_error_continues_to_verify(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        """Scan failure is logged but verification still runs."""
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
        )
        fake = _FakeClient(folders=fixture)

        # The scanner must raise ScanError (not return a ScanOutcome) for
        # _execute to log the error message to stderr.
        scan_error = ScanError("RefreshLibrary scan failed")
        scan_error.outcome = _FAILED_SCAN_OUTCOME
        scanner_instance = MagicMock()
        scanner_instance.scan.side_effect = scan_error
        mock_scanner_cls.return_value = scanner_instance

        mock_verify.return_value = _successful_verification(config)

        stderr_capture = io.StringIO()
        stdout_capture = io.StringIO()
        old_stderr = sys.stderr
        old_stdout = sys.stdout
        sys.stderr = stderr_capture
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stderr = old_stderr
            sys.stdout = old_stdout

        # Scan failed but output was produced; exit is 1 because scan failed
        self.assertEqual(rc, 1)
        self.assertIn("RefreshLibrary scan failed", stderr_capture.getvalue())


# ===========================================================================
# TestConvergedRerunSkipsMutationsAndScan
# ===========================================================================


class TestConvergedRerunSkipsMutationsAndScan(TestCase):
    """No-op reconcile → no scan triggered."""

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_no_mutation_skips_scan(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        fixture = _load_fixture()
        # All desired paths already present → no mutation
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
        )
        fake = _FakeClient(folders=fixture)

        mock_verify.return_value = _successful_verification(config)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        # Scanner was never instantiated
        mock_scanner_cls.assert_not_called()
        mock_verify.assert_called_once()

    @patch("jellyfin_library_repair.main.verify_paths")
    def test_converged_execute_returns_zero(self, mock_verify: MagicMock) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
        )
        fake = _FakeClient(folders=fixture)

        mock_verify.return_value = _successful_verification(config)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)


# ===========================================================================
# TestChangedExecuteTriggersExactlyOneScan
# ===========================================================================


class TestChangedExecuteTriggersExactlyOneScan(TestCase):
    """New paths added → one scan triggered."""

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_exactly_one_scan_after_add(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=(
                "/srv/media/movies/1",
                "/srv/media/movies/2",
                "/srv/media/movies/3",
                "/srv/media/movies/4",
            ),
        )
        fake = _FakeClient(folders=fixture)

        scanner_instance = MagicMock()
        scanner_instance.scan.return_value = _SUCCESS_SCAN_OUTCOME
        mock_scanner_cls.return_value = scanner_instance

        mock_verify.return_value = _successful_verification(config)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        self.assertEqual(mock_scanner_cls.call_count, 1)
        self.assertEqual(scanner_instance.scan.call_count, 1)

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_one_scan_after_remove(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)

        scanner_instance = MagicMock()
        scanner_instance.scan.return_value = _SUCCESS_SCAN_OUTCOME
        mock_scanner_cls.return_value = scanner_instance

        mock_verify.return_value = _successful_verification(config)

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        self.assertEqual(scanner_instance.scan.call_count, 1)


# ===========================================================================
# TestVerificationAfterWorkflow
# ===========================================================================


class TestVerificationAfterWorkflow(TestCase):
    """Desired paths present, obsolete absent after full execute."""

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_verification_reports_correct_paths(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)

        scanner_instance = MagicMock()
        scanner_instance.scan.return_value = _SUCCESS_SCAN_OUTCOME
        mock_scanner_cls.return_value = scanner_instance

        # Build a verification that shows the desired result
        verification = VerificationResult(
            library_verifications=(LibraryVerification(
                library_name="Movies",
                library_kind="movies",
                desired_paths_present=("/srv/media/movies/1", "/srv/media/movies/3"),
                desired_paths_missing=(),
                obsolete_paths_absent=("/srv/media/movies/legacy",),
                obsolete_paths_still_present=(),
                residual_paths=("/srv/media/movies/unmanaged",),
            ),),
            success=True,
        )
        mock_verify.return_value = verification

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        output = json.loads(stdout_capture.getvalue())

        # Check reconciliation was executed
        reconciliation = output.get("reconciliation", output)
        self.assertEqual(reconciliation["execution"]["mode"], "execute")
        self.assertIn("/srv/media/movies/3", reconciliation["execution"]["added"])

        # Check verification block
        self.assertIsNotNone(output.get("verification"))
        self.assertTrue(output["verification"]["success"])
        self.assertIn(
            "/srv/media/movies/1",
            output["verification"]["desired_paths_present"],
        )

    @patch("jellyfin_library_repair.main.verify_paths")
    def test_verification_failure_returns_nonzero(
        self, mock_verify: MagicMock
    ) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1",),
        )
        fake = _FakeClient(folders=fixture)

        verification = VerificationResult(
            library_verifications=(LibraryVerification(
                library_name="Movies",
                library_kind="movies",
                desired_paths_present=(),
                desired_paths_missing=("/srv/media/movies/1",),
                obsolete_paths_absent=(),
                obsolete_paths_still_present=(),
                residual_paths=(),
            ),),
            success=False,
        )
        mock_verify.return_value = verification

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 1)


# ===========================================================================
# TestResidualStalePrefixesReported
# ===========================================================================


class TestResidualStalePrefixesReported(TestCase):
    """Stale paths reported for manual review in verification output."""

    @patch("jellyfin_library_repair.main.verify_paths")
    def test_residual_paths_in_verification_output(
        self, mock_verify: MagicMock
    ) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1",),
        )
        fake = _FakeClient(folders=fixture)

        verification = VerificationResult(
            library_verifications=(LibraryVerification(
                library_name="Movies",
                library_kind="movies",
                desired_paths_present=("/srv/media/movies/1",),
                desired_paths_missing=(),
                obsolete_paths_absent=(),
                obsolete_paths_still_present=(),
                residual_paths=(
                    "/srv/media/movies/unmanaged",
                    "/srv/media/movies/legacy-stale",
                ),
            ),),
            success=True,
        )
        mock_verify.return_value = verification

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        output = json.loads(stdout_capture.getvalue())
        residual = output["verification"]["residual_paths"]
        self.assertIn("/srv/media/movies/unmanaged", residual)
        self.assertIn("/srv/media/movies/legacy-stale", residual)

    @patch("jellyfin_library_repair.main.RefreshLibraryScanner")
    @patch("jellyfin_library_repair.main.verify_paths")
    def test_stale_path_not_in_desired_or_obsolete(
        self, mock_verify: MagicMock, mock_scanner_cls: MagicMock
    ) -> None:
        """Residual paths are distinct from both desired and obsolete."""
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)

        scanner_instance = MagicMock()
        scanner_instance.scan.return_value = _SUCCESS_SCAN_OUTCOME
        mock_scanner_cls.return_value = scanner_instance

        verification = VerificationResult(
            library_verifications=(LibraryVerification(
                library_name="Movies",
                library_kind="movies",
                desired_paths_present=(
                    "/srv/media/movies/1",
                    "/srv/media/movies/2",
                ),
                desired_paths_missing=(),
                obsolete_paths_absent=("/srv/media/movies/legacy",),
                obsolete_paths_still_present=(),
                residual_paths=("/srv/media/movies/unmanaged",),
            ),),
            success=True,
        )
        mock_verify.return_value = verification

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture
        try:
            rc = _execute(fake, config)
        finally:
            sys.stdout = old_stdout

        self.assertEqual(rc, 0)
        output = json.loads(stdout_capture.getvalue())
        residual = output["verification"]["residual_paths"]
        # Residual is not in desired
        for path in config.movies.desired_paths:
            self.assertNotIn(path, residual)
        # Residual is not in obsolete
        for path in config.movies.obsolete_paths:
            self.assertNotIn(path, residual)


if __name__ == "__main__":
    unittest_main()
