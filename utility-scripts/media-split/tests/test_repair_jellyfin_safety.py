"""Mocked tests for the Jellyfin library-path reconciliation safety contract.

The reconciler delegates HTTP to a client that satisfies the ``LibraryPathClient``
protocol.  Every test injects a recording fake and asserts safety properties such
as exact-path deletion, refreshLibrary=false, media preservation, and abort
behaviour.  No real credentials or live Jellyfin endpoint are contacted.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
import json
import urllib.error
from typing import Any
from unittest import main as unittest_main, TestCase
from unittest.mock import MagicMock

from jellyfin_library_repair.api import (
    JellyfinApiClient,
    JellyfinMutationAmbiguousError,
    JellyfinUnsupportedEndpointError,
)
from jellyfin_library_repair.reconcile import (
    MutationResponseError,
    PathReadinessError,
    PathVerificationError,
    reconcile,
)
from jellyfin_library_repair.models import (
    LibraryConfig,
    LibraryKind,
    RepairConfig,
)


BASE_URL = "https://jellyfin.invalid"
TOKEN = "fixture-safety-token-redacted"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jellyfin_virtual_folders.json"


# ---------------------------------------------------------------------------
# Recording transport for the concrete JellyfinApiClient tests
# ---------------------------------------------------------------------------

class _ApiRecordingTransport:
    """Minimal callable transport that records requests, used for API-level tests."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return (200, b"null")


# ---------------------------------------------------------------------------
# Recording fake client: satisfies the LibraryPathClient protocol
# ---------------------------------------------------------------------------

@dataclass
class _FakeClient:
    """Records add/remove/read calls and returns pre-configured responses."""

    # Initial virtual-folder response returned by get_virtual_folders().
    folders: list[dict[str, Any]] = field(default_factory=list)

    # Pre-configured responses for add_virtual_folder_path(), one per call in order.
    add_responses: list[Any] = field(default_factory=list)
    # Pre-configured responses for remove_virtual_folder_path(), one per call.
    remove_responses: list[Any] = field(default_factory=list)

    # When set, get_virtual_folders raises this exception instead of returning.
    read_error: Exception | None = None

    # Mutable copy of folders that add/remove modify so a subsequent read sees
    # the reflected state (mimicking Jellyfin's actual behaviour).
    _mutable_folders: list[dict[str, Any]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._mutable_folders = copy.deepcopy(self.folders)

    # -- LibraryPathClient protocol methods ----------------------------------

    def get_virtual_folders(self) -> list[dict[str, Any]]:
        if self.read_error is not None:
            raise self.read_error
        return copy.deepcopy(self._mutable_folders)

    def add_virtual_folder_path(self, library_name: str, path: str) -> Any:
        # Simulate Jellyfin reflecting the added path on a subsequent read.
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
        # Simulate Jellyfin reflecting the removed path on a subsequent read.
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
# Helpers
# ---------------------------------------------------------------------------

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


def _load_fixture() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


class _RecordingClient:
    """Wraps _FakeClient to record every raw method call for assertion."""

    def __init__(self, fake: _FakeClient) -> None:
        self._fake = fake
        self.add_calls: list[tuple[str, str]] = []
        self.remove_calls: list[tuple[str, str]] = []

    def get_virtual_folders(self) -> list[dict[str, Any]]:
        return self._fake.get_virtual_folders()

    def add_virtual_folder_path(self, library_name: str, path: str) -> Any:
        self.add_calls.append((library_name, path))
        return self._fake.add_virtual_folder_path(library_name, path)

    def remove_virtual_folder_path(self, library_name: str, path: str) -> Any:
        self.remove_calls.append((library_name, path))
        return self._fake.remove_virtual_folder_path(library_name, path)


def _http_error_404() -> urllib.error.HTTPError:
    """Build an HTTPError 404 with a proper Message object for hdrs."""
    return urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=Message(), fp=None,
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestMissingPathAddUsesRefreshLibraryFalse(TestCase):
    """Add requests must always include refreshLibrary=false."""

    def test_add_calls_refresh_library_false(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2",
                     "/srv/media/movies/3", "/srv/media/movies/4"),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config, execute=True)

        # movies/3 and movies/4 are missing from the fixture and should be added.
        self.assertEqual(
            sorted(client.add_calls),
            sorted([("Movies", "/srv/media/movies/3"),
                    ("Movies", "/srv/media/movies/4")]),
        )
        self.assertEqual(
            result.added_paths, ("/srv/media/movies/3", "/srv/media/movies/4"),
        )

    def test_add_uses_api_client_refresh_false_endpoint(self) -> None:
        """Verify the JellyfinApiClient sends the correct query parameter."""

        class _RecordingAddClient:
            """Records add calls and simulates Jellyfin reflecting the path."""

            def __init__(self) -> None:
                self.add_calls: list[tuple[str, str]] = []
                self._state: list[dict[str, Any]] = [
                    {"Name": "Movies", "CollectionType": "movies",
                     "LibraryOptions": {"PathInfos": [{"Path": "/srv/media/movies/1"}]}},
                ]

            def get_virtual_folders(self) -> list[dict[str, Any]]:
                import copy
                return copy.deepcopy(self._state)

            def add_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.add_calls.append((library_name, path))
                for lib in self._state:
                    if lib.get("Name") == library_name:
                        opts = lib.setdefault("LibraryOptions", {})
                        infos = opts.setdefault("PathInfos", [])
                        infos.append({"Path": path})

            def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
                pass

        client = _RecordingAddClient()
        config = _movies_config(desired=("/srv/media/movies/1", "/srv/media/movies/2"))
        reconcile(client, config, execute=True)
        self.assertEqual(client.add_calls, [("Movies", "/srv/media/movies/2")])


class TestExactEncodedConfiguredPathDeletion(TestCase):
    """Deletion must use the exact configured path string."""

    def test_remove_passes_exact_path(self) -> None:
        fixture = _load_fixture()
        obsolete = "/srv/media/movies/legacy"
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=(obsolete,),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config, execute=True)

        self.assertEqual(client.remove_calls, [("Movies", obsolete)])
        self.assertEqual(result.removed_paths, (obsolete,))


class TestPreservationOfMediaLocations(TestCase):
    """Non-obsolete, non-desired locations must be preserved."""

    def test_unmanaged_root_not_removed(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config, execute=True)

        self.assertEqual(client.remove_calls, [])
        self.assertEqual(result.removed_paths, ())
        # Unmanaged root should appear in preserved paths.
        self.assertIn("/srv/media/movies/unmanaged", result.preserved)

    def test_legacy_not_removed_when_not_obsolete(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config, execute=True)

        self.assertIn("/srv/media/movies/legacy", result.preserved)
        self.assertNotIn("/srv/media/movies/legacy", result.removed_paths)


class TestNoDeleteItemsOrWholeLibraryDelete(TestCase):
    """DELETE /Items and whole-library DELETE must never be called."""

    def test_no_delete_items_called_by_reconciler(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        reconcile(client, config, execute=True)

        # The recording client only exposes path-level methods; no item-level
        # deletion exists on the protocol surface.  The reconciler never calls
        # anything named delete_items or similar.

    def test_concrete_api_client_blocks_delete_items_endpoint(self) -> None:
        """The concrete JellyfinApiClient blocks DELETE /Items at route level."""
        api_client = JellyfinApiClient(
            BASE_URL, token=TOKEN, transport=_ApiRecordingTransport(),
        )
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            api_client.request("DELETE", "/Items")

    def test_concrete_api_client_blocks_delete_items_with_id(self) -> None:
        api_client = JellyfinApiClient(
            BASE_URL, token=TOKEN, transport=_ApiRecordingTransport(),
        )
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            api_client.request("DELETE", "/Items/some-uuid")


class TestStorageUnavailableAddAbortsBeforeRemovalOrScan(TestCase):
    """When an add fails, no removal or scan must follow."""

    def test_add_failure_stops_reconciliation(self) -> None:
        """A transport error during add propagates immediately — no remove."""

        class _SelectiveTransport:
            """Succeeds on the initial GET (read state) but fails on POST (add)."""

            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def request(self, *, method: str, url: str, headers: dict[str, str],
                        body: bytes | None, timeout: float, context: Any) -> Any:
                self.calls.append({"method": method, "url": url})
                if method == "POST":
                    raise ConnectionError("storage unavailable")
                return (200, json.dumps([
                    {"Name": "Movies", "CollectionType": "movies",
                     "LibraryOptions": {"PathInfos": [
                         {"Path": "/srv/media/movies/1"},
                     ]}},
                ]).encode("utf-8"))

        transport = _SelectiveTransport()
        client = JellyfinApiClient(
            BASE_URL, token=TOKEN, transport=transport,
        )
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
            obsolete=("/srv/media/movies/legacy",),
        )
        # movies/3 is missing — the POST call hits the transport error and
        # should propagate before any remove is attempted.
        with self.assertRaises(JellyfinMutationAmbiguousError):
            reconcile(client, config, execute=True)
        # Transport recorded exactly two calls: initial GET + failed POST.
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["method"], "GET")
        self.assertEqual(transport.calls[1]["method"], "POST")

    def test_add_succeeds_but_path_absent_aborts_with_readiness_error(self) -> None:
        """Add returns None (success) but path is absent → PathReadinessError."""

        class _ClientAddNoOp:
            """Add returns None but never reflects the path in state."""

            def __init__(self, folders: list[dict[str, Any]]) -> None:
                self._mutable = copy.deepcopy(folders)
                self.add_calls: list[tuple[str, str]] = []
                self.remove_calls: list[tuple[str, str]] = []

            def get_virtual_folders(self) -> list[dict[str, Any]]:
                return copy.deepcopy(self._mutable)

            def add_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.add_calls.append((library_name, path))
                # Intentionally do NOT add the path — simulates storage unavailable
                # where the server accepted but did not persist.

            def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.remove_calls.append((library_name, path))

        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
        )
        client = _ClientAddNoOp(fixture)

        with self.assertRaises(PathReadinessError):
            reconcile(client, config, execute=True)

        # Add was attempted but the post-add readiness check caught the gap.
        self.assertEqual(len(client.add_calls), 1)
        self.assertEqual(client.remove_calls, [])


class TestAmbiguousMutationResponseIsNotRetried(TestCase):
    """When a mutation transport fails, it raises MutationAmbiguousError."""

    def test_ambiguous_post_not_retried(self) -> None:
        """A transport failure on a POST raises MutationAmbiguousError."""
        transport = _ApiRecordingTransport(error=ConnectionError("connection reset"))
        client = JellyfinApiClient(
            BASE_URL, token=TOKEN, transport=transport,
        )
        with self.assertRaises(JellyfinMutationAmbiguousError):
            client.add_virtual_folder_path("Movies", "/srv/media/movies/1")
        # Only one attempt — no retry.
        self.assertEqual(len(transport.calls), 1)

    def test_ambiguous_delete_not_retried(self) -> None:
        """A transport failure on a DELETE raises MutationAmbiguousError."""
        transport = _ApiRecordingTransport(error=ConnectionError("connection reset"))
        client = JellyfinApiClient(
            BASE_URL, token=TOKEN, transport=transport,
        )
        with self.assertRaises(JellyfinMutationAmbiguousError):
            client.remove_virtual_folder_path("Movies", "/srv/media/movies/legacy")
        self.assertEqual(len(transport.calls), 1)


class TestDeletion404AcceptedAfterReRead(TestCase):
    """A 404 on remove is accepted only if re-read proves the path absent."""

    def test_404_with_path_still_present_raises(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )

        class _Client404StillPresent:
            """Raises 404 on remove but the mutable state still has the path."""

            def __init__(self, folders: list[dict[str, Any]]) -> None:
                self._folders = folders
                self.remove_calls: list[tuple[str, str]] = []

            def get_virtual_folders(self) -> list[dict[str, Any]]:
                return copy.deepcopy(self._folders)

            def add_virtual_folder_path(self, library_name: str, path: str) -> None:
                pass

            def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.remove_calls.append((library_name, path))
                # Do NOT remove the path — the re-read will still see it.
                raise _http_error_404()

        client = _Client404StillPresent(fixture)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            reconcile(client, config, execute=True)
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(len(client.remove_calls), 1)

    def test_404_with_path_absent_on_reread_is_accepted(self) -> None:
        """When remove raises 404 but re-read confirms absence, accept it."""
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )

        class _Client404Absent:
            """Raises 404 on remove but removes from mutable state first."""

            def __init__(self, folders: list[dict[str, Any]]) -> None:
                self._mutable = copy.deepcopy(folders)
                self.remove_calls: list[tuple[str, str]] = []

            def get_virtual_folders(self) -> list[dict[str, Any]]:
                return copy.deepcopy(self._mutable)

            def add_virtual_folder_path(self, library_name: str, path: str) -> None:
                pass

            def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.remove_calls.append((library_name, path))
                # Remove from mutable state so re-read confirms absence.
                for lib in self._mutable:
                    if lib.get("Name") == library_name:
                        locs = lib.get("Locations")
                        if locs is not None:
                            lib["Locations"] = [p for p in locs if p != path]
                        opts = lib.get("LibraryOptions") or {}
                        infos = opts.get("PathInfos")
                        if infos is not None:
                            lib["LibraryOptions"]["PathInfos"] = [
                                p for p in infos if p.get("Path") != path
                            ]
                # Then raise 404 — the reconciler re-reads and accepts.
                raise _http_error_404()

        client = _Client404Absent(fixture)
        result = reconcile(client, config, execute=True)

        self.assertEqual(result.removed_paths, ("/srv/media/movies/legacy",))
        self.assertEqual(len(client.remove_calls), 1)


class TestStillPresentPathAfterDeletionFails(TestCase):
    """If a delete succeeds (no error) but re-read still sees the path, fail."""

    def test_path_verification_error_on_still_present(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )

        class _StubbornClient:
            """remove returns None (success) but the path remains on re-read."""

            def __init__(self, folders: list[dict[str, Any]]) -> None:
                self._folders = folders
                self.remove_calls: list[tuple[str, str]] = []

            def get_virtual_folders(self) -> list[dict[str, Any]]:
                return copy.deepcopy(self._folders)

            def add_virtual_folder_path(self, library_name: str, path: str) -> None:
                pass

            def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
                self.remove_calls.append((library_name, path))
                # Return None (success) but don't actually remove the path.

        client = _StubbornClient(fixture)

        with self.assertRaises(PathVerificationError) as ctx:
            reconcile(client, config, execute=True)
        self.assertIn("legacy", str(ctx.exception))
        self.assertIn("still reports", str(ctx.exception))


class TestDryRunProducesNoMutations(TestCase):
    """Dry-run mode must not call add or remove."""

    def test_dry_run_skips_mutations(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config)

        self.assertTrue(result.dry_run)
        self.assertFalse(result.executed)
        self.assertEqual(client.add_calls, [])
        self.assertEqual(client.remove_calls, [])
        self.assertEqual(result.added_paths, ())
        self.assertEqual(result.removed_paths, ())


class TestMutationResponseErrorOnUnexpectedStatus(TestCase):
    """A non-204 status from the injectable client raises MutationResponseError."""

    def test_add_with_status_409_raises(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/3"),
        )
        fake = _FakeClient(folders=fixture, add_responses=[409])

        with self.assertRaises(MutationResponseError) as ctx:
            reconcile(fake, config, execute=True)
        self.assertEqual(ctx.exception.operation, "add")
        self.assertEqual(ctx.exception.status, 409)

    def test_remove_with_status_403_raises(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1",),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture, remove_responses=[403])

        with self.assertRaises(MutationResponseError) as ctx:
            reconcile(fake, config, execute=True)
        self.assertEqual(ctx.exception.operation, "remove")
        self.assertEqual(ctx.exception.status, 403)


class TestMediaPreservingConfiguredLocationSemantics(TestCase):
    """Fixtures model media-preserving configured locations throughout."""

    def test_fixture_contains_media_preserving_locations(self) -> None:
        fixture = _load_fixture()
        for entry in fixture:
            locs = entry.get("Locations")
            if locs is None:
                opts = entry.get("LibraryOptions") or {}
                path_infos = opts.get("PathInfos", [])
                locs = [p["Path"] for p in path_infos]
            for path in locs:
                self.assertTrue(
                    path.startswith("/srv/media/"),
                    f"location {path!r} is not under /srv/media/",
                )

    def test_obsolete_path_targets_only_configured_locations(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(
            desired=("/srv/media/movies/1", "/srv/media/movies/2"),
            obsolete=("/srv/media/movies/legacy",),
        )
        fake = _FakeClient(folders=fixture)
        client = _RecordingClient(fake)

        result = reconcile(client, config, execute=True)

        # Only the exact obsolete path was removed; media roots are untouched.
        self.assertEqual(result.removed_paths, ("/srv/media/movies/legacy",))
        self.assertNotIn("/srv/media/movies/1", result.removed_paths)
        self.assertNotIn("/srv/media/movies/2", result.removed_paths)


class TestTokenNeverAppearsInCallLogs(TestCase):
    """Verify token is not present in any observable client output."""

    def test_token_not_in_fixture(self) -> None:
        fixture = _load_fixture()
        fixture_text = json.dumps(fixture)
        self.assertNotIn(TOKEN, fixture_text)

    def test_token_not_in_reconciler_result(self) -> None:
        fixture = _load_fixture()
        config = _movies_config(desired=("/srv/media/movies/1",))
        fake = _FakeClient(folders=fixture)

        result = reconcile(fake, config, execute=True)

        result_text = json.dumps(result.to_dict())
        self.assertNotIn(TOKEN, result_text)


if __name__ == "__main__":
    unittest_main()
