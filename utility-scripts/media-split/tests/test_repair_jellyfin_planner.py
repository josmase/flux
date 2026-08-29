"""Unit tests for the side-effect-free Jellyfin CLI and reconciliation planner.

The fixture is a sanitized local capture.  These tests deliberately exercise
the parser and pure planner only; no Jellyfin, Kubernetes, filesystem mount,
or credential provider is contacted.
"""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from typing import cast
import unittest
from unittest.mock import patch

from jellyfin_library_repair import (
    DecisionAction,
    LibraryConfig,
    LibraryKind,
    PlanningError,
    RepairConfig,
    plan_reconciliation,
)
from jellyfin_library_repair.cli import CliValidationError, main, parse_cli


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jellyfin_virtual_folders.json"
BASE_URL = "https://jellyfin.invalid"


class RepairJellyfinPlannerTests(unittest.TestCase):
    """Behavioral coverage for subtask 01's CLI and planner contract."""

    @classmethod
    def setUpClass(cls) -> None:
        # Arrange: load one deterministic, sanitized GET /Library/VirtualFolders
        # capture for every test rather than reaching a live service.
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            cls.fixture = json.load(handle)

    def _base_cli_args(self) -> list[str]:
        return [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--series-library",
            "Series",
        ]

    def _library(
        self,
        kind: LibraryKind,
        name: str,
        collection_type: str,
        desired_paths: tuple[str, ...],
        obsolete_paths: tuple[str, ...] = (),
    ) -> LibraryConfig:
        return LibraryConfig(
            kind=kind,
            name=name,
            collection_type=collection_type,
            desired_paths=desired_paths,
            obsolete_paths=obsolete_paths,
        )

    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(argv)
        return result, output.getvalue()

    def test_sanitized_fixture_contains_local_library_state_only(self) -> None:
        # Arrange: the fixture is the only current-state input used by this suite.
        fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")

        # Act: parse the capture exactly as the CLI does.
        payload = json.loads(fixture_text)

        # Assert: it has useful library data but no credential or live endpoint material.
        self.assertEqual([entry["Name"] for entry in payload], ["Movies", "Series", "Music"])
        self.assertNotIn("Authorization", fixture_text)
        self.assertNotIn("password", fixture_text.lower())
        self.assertNotIn("api_key", fixture_text.lower())
        self.assertTrue(
            all(
                location.startswith("/srv/media/")
                for entry in payload
                for location in (
                    entry.get("Locations")
                    or [item["Path"] for item in entry["LibraryOptions"]["PathInfos"]]
                )
            )
        )

    def test_cli_accepts_repeatable_variable_movie_and_series_shards(self) -> None:
        # Arrange: use twelve movie roots and six series roots, not a fixed 3/2 topology.
        movie_paths = tuple(f"/srv/media/movies/{number}" for number in range(1, 13))
        series_paths = tuple(f"/srv/media/series/{number}" for number in range(1, 7))
        argv = self._base_cli_args()
        for path in movie_paths:
            argv.extend(("--movies-path", path))
        for path in series_paths:
            argv.extend(("--series-path", path))
        argv.extend(
            (
                "--movies-collection-type",
                "movies",
                "--series-collection-type",
                "tvshows",
            )
        )

        # Act: parse all repeated desired-path options.
        parsed = parse_cli(argv)
        movies = cast(LibraryConfig, parsed.config.movies_library)
        series = cast(LibraryConfig, parsed.config.series_library)

        # Assert: every requested shard survives validation in input order and dry-run is default.
        self.assertEqual(movies.desired_paths, movie_paths)
        self.assertEqual(series.desired_paths, series_paths)
        self.assertEqual(len(movies.desired_paths), 12)
        self.assertEqual(len(series.desired_paths), 6)
        self.assertTrue(parsed.config.dry_run)
        self.assertFalse(parsed.config.execute)

    def test_cli_accepts_explicit_execute_mode_without_contacting_a_client(self) -> None:
        # Arrange: authorize execute explicitly while still supplying only local CLI data.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--execute",
        ]

        # Act: validate the execute configuration without constructing an API client.
        parsed = parse_cli(argv)

        # Assert: execute is opt-in and mutually exclusive with the default dry-run state.
        self.assertEqual(parsed.config.mode, "execute")
        self.assertFalse(parsed.config.dry_run)
        self.assertTrue(parsed.config.execute)

    def test_planner_builds_variable_shard_plan_for_both_libraries(self) -> None:
        # Arrange: current state has fewer numbered roots than the requested topology.
        movie_paths = tuple(f"/srv/media/movies/{number}" for number in range(1, 13))
        series_paths = tuple(f"/srv/media/series/{number}" for number in range(1, 7))
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(LibraryKind.MOVIES, "Movies", "movies", movie_paths),
            series=self._library(LibraryKind.SERIES, "Series", "tvshows", series_paths),
        )

        # Act: build a plan from the local capture without a client.
        before = copy.deepcopy(self.fixture)
        plan = plan_reconciliation(config, self.fixture)

        # Assert: missing roots are added regardless of shard count and input state is untouched.
        self.assertEqual(
            plan.plans[0].add_paths,
            tuple(
                sorted(f"/srv/media/movies/{number}" for number in range(3, 13))
            ),
        )
        self.assertEqual(
            plan.plans[1].add_paths,
            tuple(f"/srv/media/series/{number}" for number in range(4, 7)),
        )
        self.assertEqual(plan.remove_paths, ())
        self.assertTrue(plan.scan_required)
        self.assertEqual(self.fixture, before)

    def test_planner_matches_library_name_and_collection_type(self) -> None:
        # Arrange: select the Movies virtual folder with its expected collection type.
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(
                LibraryKind.MOVIES,
                "Movies",
                "movies",
                ("/srv/media/movies/1",),
            ),
        )

        # Act: match the selected library in the sanitized response.
        plan = plan_reconciliation(config, self.fixture)

        # Assert: the named, correctly typed folder is planned and unrelated Music is ignored.
        movie_plan = plan.plans[0]
        self.assertEqual(movie_plan.library.kind, LibraryKind.MOVIES)
        self.assertEqual(movie_plan.library.name, "Movies")
        self.assertEqual(movie_plan.library.collection_type, "movies")
        self.assertIn("/srv/media/movies/1", movie_plan.preserve_paths)
        self.assertNotIn("/srv/media/music", movie_plan.current_paths)

    def test_planner_rejects_selected_library_with_wrong_collection_type(self) -> None:
        # Arrange: keep the requested name but make the selected current folder a series type.
        current = copy.deepcopy(self.fixture)
        current[0]["CollectionType"] = "tvshows"
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(
                LibraryKind.MOVIES,
                "Movies",
                "movies",
                ("/srv/media/movies/1",),
            ),
        )

        # Act and assert: strict collection-type matching fails before any plan mutation.
        with self.assertRaisesRegex(PlanningError, "collection type"):
            plan_reconciliation(config, current)

    def test_planner_removes_only_an_explicit_obsolete_location(self) -> None:
        # Arrange: mark exactly the legacy location obsolete while retaining desired roots.
        obsolete_path = "/srv/media/movies/legacy"
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(
                LibraryKind.MOVIES,
                "Movies",
                "movies",
                ("/srv/media/movies/1", "/srv/media/movies/2"),
                (obsolete_path,),
            ),
        )

        # Act: reconcile against the current movie locations.
        movie_plan = plan_reconciliation(config, self.fixture).plans[0]

        # Assert: removal is exact and explicit; no omitted root is implicitly removed.
        self.assertEqual(movie_plan.add_paths, ())
        self.assertEqual(movie_plan.remove_paths, (obsolete_path,))
        removal = next(
            decision
            for decision in movie_plan.decisions
            if decision.action is DecisionAction.REMOVE
        )
        self.assertTrue(removal.explicit)
        self.assertEqual(removal.reason, "path is explicitly listed as obsolete")
        self.assertIn("/srv/media/movies/unmanaged", movie_plan.preserve_paths)
        self.assertNotIn("/srv/media/movies/unmanaged", movie_plan.remove_paths)
        self.assertTrue(movie_plan.scan_required)

    def test_planner_preserves_current_roots_omitted_from_desired_state(self) -> None:
        # Arrange: omit both the legacy and unmanaged roots without declaring either obsolete.
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(
                LibraryKind.MOVIES,
                "Movies",
                "movies",
                ("/srv/media/movies/1", "/srv/media/movies/2"),
            ),
        )

        # Act: create the no-op plan for the already configured numbered roots.
        movie_plan = plan_reconciliation(config, self.fixture).plans[0]

        # Assert: omitted current locations remain preserved and no scan is needed.
        self.assertEqual(movie_plan.remove_paths, ())
        self.assertEqual(movie_plan.add_paths, ())
        self.assertEqual(
            movie_plan.preserve_paths,
            (
                "/srv/media/movies/1",
                "/srv/media/movies/2",
                "/srv/media/movies/legacy",
                "/srv/media/movies/unmanaged",
            ),
        )
        self.assertFalse(movie_plan.scan_required)

    def test_planner_does_not_remove_an_obsolete_location_that_is_not_current(self) -> None:
        # Arrange: explicitly name a path that is absent from the current Jellyfin state.
        config = RepairConfig(
            base_url=BASE_URL,
            movies=self._library(
                LibraryKind.MOVIES,
                "Movies",
                "movies",
                ("/srv/media/movies/1", "/srv/media/movies/2"),
                ("/srv/media/movies/not-configured",),
            ),
        )

        # Act: build the plan without contacting Jellyfin.
        movie_plan = plan_reconciliation(config, self.fixture).plans[0]

        # Assert: an absent obsolete request creates no removal or unnecessary scan.
        self.assertEqual(movie_plan.remove_paths, ())
        self.assertFalse(movie_plan.scan_required)
        self.assertIn("/srv/media/movies/legacy", movie_plan.preserve_paths)

    def test_cli_rejects_library_without_a_desired_path(self) -> None:
        # Arrange: select a library but provide no repeatable desired path.
        argv = ["--base-url", BASE_URL, "--movies-library", "Movies"]

        # Act and assert: validation fails before a RepairConfig can be created.
        with self.assertRaisesRegex(CliValidationError, "at least one"):
            parse_cli(argv)

    def test_cli_rejects_paths_without_a_library(self) -> None:
        # Arrange: provide a movie path without selecting a movie library.
        argv = ["--base-url", BASE_URL, "--movies-path", "/srv/media/movies/1"]

        # Act and assert: path ownership is required at the CLI boundary.
        with self.assertRaisesRegex(CliValidationError, "require --movies-library"):
            parse_cli(argv)

    def test_cli_rejects_empty_path(self) -> None:
        # Arrange: an empty argument is not a usable absolute path.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "",
        ]

        # Act and assert: empty path input is rejected as configuration error.
        with self.assertRaisesRegex(CliValidationError, "non-empty string"):
            parse_cli(argv)

    def test_cli_rejects_relative_path(self) -> None:
        # Arrange: Jellyfin locations must be absolute POSIX paths.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "movies/1",
        ]

        # Act and assert: relative paths cannot reach the planner.
        with self.assertRaisesRegex(CliValidationError, "absolute path"):
            parse_cli(argv)

    def test_cli_rejects_duplicate_desired_paths(self) -> None:
        # Arrange: repeat the same desired location for one library.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--movies-path",
            "/srv/media/movies/1",
        ]

        # Act and assert: duplicate roots are rejected deterministically.
        with self.assertRaisesRegex(CliValidationError, "duplicate"):
            parse_cli(argv)

    def test_cli_rejects_path_declared_both_desired_and_obsolete(self) -> None:
        # Arrange: the same exact path appears in both sides of the request.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--movies-obsolete-path",
            "/srv/media/movies/1",
        ]

        # Act and assert: contradictory desired state is rejected before planning.
        with self.assertRaisesRegex(CliValidationError, "both desired and obsolete"):
            parse_cli(argv)

    def test_cli_rejects_combined_dry_run_and_execute_flags(self) -> None:
        # Arrange: both mutually exclusive authorization modes are requested.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--dry-run",
            "--execute",
        ]
        errors = io.StringIO()

        # Act: argparse reports the invalid flag combination.
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            parse_cli(argv)

        # Assert: the parser exits with its standard usage-error status and no client exists.
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("not allowed with argument", errors.getvalue())

    def test_cli_rejects_incomplete_cluster_credential_reference(self) -> None:
        # Arrange: cluster mode is explicit but the Secret key is omitted.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--from-cluster",
            "--cluster-secret",
            "jellyfin-repair",
        ]

        # Act and assert: incomplete secret metadata fails before any lookup.
        with self.assertRaisesRegex(CliValidationError, "requires --cluster-secret and --cluster-key"):
            parse_cli(argv)

    def test_cli_rejects_cluster_options_without_from_cluster(self) -> None:
        # Arrange: a Secret name without explicit cluster mode is ambiguous and unsafe.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--cluster-secret",
            "jellyfin-repair",
            "--cluster-key",
            "api-key",
        ]

        # Act and assert: no implicit Kubernetes dependency is allowed.
        with self.assertRaisesRegex(CliValidationError, "require --from-cluster"):
            parse_cli(argv)

    def test_cli_accepts_cluster_reference_without_secret_value(self) -> None:
        # Arrange: provide only sanitized Kubernetes Secret lookup metadata.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--from-cluster",
            "--cluster-secret",
            "jellyfin-repair",
            "--cluster-key",
            "api-key",
        ]

        # Act: parse without resolving a Kubernetes Secret.
        parsed = parse_cli(argv)

        # Assert: only non-secret lookup references are retained.
        self.assertEqual(parsed.config.credential_source.kind, "cluster-secret")
        self.assertEqual(
            parsed.config.credential_source.to_public_dict(),
            {
                "type": "cluster-secret",
                "namespace": "media",
                "secret_name": "jellyfin-repair",
                "secret_key": "api-key",
            },
        )

    def test_cli_rejects_credentials_in_base_url(self) -> None:
        # Arrange: the URL contains clearly synthetic userinfo, which must never be accepted.
        argv = [
            "--base-url",
            "https://fixture-user:fixture-value@jellyfin.invalid",
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
        ]

        # Act and assert: credentials are rejected at URL validation.
        with self.assertRaisesRegex(CliValidationError, "must not contain credentials"):
            parse_cli(argv)

    def test_cli_rejects_insecure_tls_combined_with_ca_file(self) -> None:
        # Arrange: TLS options conflict and must be resolved before execution.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
            "--ca-file",
            "/srv/fixtures/ca.pem",
            "--insecure",
        ]

        # Act and assert: unsafe TLS combination is rejected deterministically.
        with self.assertRaisesRegex(CliValidationError, "cannot be combined"):
            parse_cli(argv)

    def test_main_defaults_to_dry_run_and_reads_no_live_dependency_without_capture(self) -> None:
        # Arrange: omit --current-state so the CLI can render configuration only.
        argv = [
            "--base-url",
            BASE_URL,
            "--movies-library",
            "Movies",
            "--movies-path",
            "/srv/media/movies/1",
        ]

        # Act: make any accidental network, subprocess, or Kubernetes call fail loudly.
        with patch("socket.create_connection", side_effect=AssertionError("network call")) as network, patch(
            "urllib.request.urlopen", side_effect=AssertionError("HTTP call")
        ) as urlopen, patch("subprocess.run", side_effect=AssertionError("subprocess call")) as run:
            result, text = self._run_main(argv)

        # Assert: default mode is read-only and no external boundary was touched.
        output = json.loads(text)
        self.assertEqual(result, 0)
        self.assertEqual(output["configuration"]["mode"], "dry-run")
        self.assertIsNone(output["plan"])
        self.assertIn("no API calls were made", output["message"])
        network.assert_not_called()
        urlopen.assert_not_called()
        run.assert_not_called()

    def test_main_emits_deterministic_complete_non_secret_dry_run_plan(self) -> None:
        # Arrange: request three movie roots, six series roots, and one explicit obsolete root.
        argv = [
            *self._base_cli_args(),
            "--movies-path",
            "/srv/media/movies/1",
            "--movies-path",
            "/srv/media/movies/2",
            "--movies-path",
            "/srv/media/movies/3",
            "--series-path",
            "/srv/media/series/1",
            "--series-path",
            "/srv/media/series/2",
            "--series-path",
            "/srv/media/series/3",
            "--series-path",
            "/srv/media/series/4",
            "--series-path",
            "/srv/media/series/5",
            "--series-path",
            "/srv/media/series/6",
            "--movies-obsolete-path",
            "/srv/media/movies/legacy",
            "--api-key-env",
            "TEST_JELLYFIN_API_KEY",
            "--current-state",
            str(FIXTURE_PATH),
        ]

        # Act: run the default dry-run twice while forbidding all live boundaries.
        with patch.dict(os.environ, {"TEST_JELLYFIN_API_KEY": "fixture-value-redacted"}), patch(
            "socket.create_connection"
        ) as network, patch("urllib.request.urlopen") as urlopen, patch(
            "subprocess.run"
        ) as run:
            first_result, first_text = self._run_main(argv)
            second_result, second_text = self._run_main(argv)

        # Assert: stable serialization contains the full plan, only references the credential,
        # and performs no network, subprocess, or mutation operation.
        first = json.loads(first_text)
        second = json.loads(second_text)
        self.assertEqual(first_result, 0)
        self.assertEqual(second_result, 0)
        self.assertEqual(first_text, second_text)
        self.assertEqual(first, second)
        self.assertEqual(first["configuration"]["mode"], "dry-run")
        self.assertEqual(first["summary"]["add_count"], 4)
        self.assertEqual(first["summary"]["remove_count"], 1)
        self.assertTrue(first["summary"]["scan_required"])
        self.assertTrue(first["scan_gate"]["required"])
        self.assertEqual(
            first["libraries"][0]["actions"]["remove"],
            ["/srv/media/movies/legacy"],
        )
        self.assertIn(
            "/srv/media/movies/unmanaged",
            first["libraries"][0]["actions"]["preserve"],
        )
        self.assertIn(
            "/srv/media/series/unmanaged",
            first["libraries"][1]["actions"]["preserve"],
        )
        self.assertNotIn("fixture-value-redacted", first_text)
        self.assertNotIn("Authorization", first_text)
        network.assert_not_called()
        urlopen.assert_not_called()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
