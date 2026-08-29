"""Unit tests for the Jellyfin RefreshLibrary scanner.

Tests cover execution-result parsing, timestamp/signature comparison,
task discovery, and the full RefreshLibraryScanner lifecycle using
injectable clock, sleeper, and lock doubles.  No real credentials,
network, or live Jellyfin are contacted.
"""

from __future__ import annotations

import copy
import errno
import io
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest import main as unittest_main, TestCase
from unittest.mock import MagicMock

from jellyfin_library_repair.scanner import (
    ExecutionResult,
    InterProcessLock,
    MalformedExecutionResultError,
    REFRESH_LIBRARY_KEY,
    RefreshLibraryScanner,
    ScanError,
    ScanLockError,
    ScanOutcome,
    ScanStartError,
    ScanTaskFailed,
    ScanTimeoutError,
    ScheduledTaskSnapshot,
    TaskDiscoveryError,
    TaskStateError,
    discover_refresh_library_task,
    is_newer_execution_result,
    parse_execution_result,
)


# ---------------------------------------------------------------------------
# Fake clock / sleeper
# ---------------------------------------------------------------------------

class _FakeClock:
    """Yields pre-configured monotonic timestamps in sequence."""

    def __init__(self, times: list[float]) -> None:
        self._times = iter(times)

    def __call__(self) -> float:
        return next(self._times)


class _RecordingSleeper:
    """Records every sleep request without blocking."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, duration: float) -> None:
        self.calls.append(duration)


class _NoopLock:
    """Context-manager lock that always succeeds — no filesystem."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> _NoopLock:
        self.entered = True
        return self

    def __exit__(self, *args: Any) -> None:
        self.exited = True


class _RejectingLock:
    """Lock that raises ScanLockError on acquire."""

    def __enter__(self) -> _RejectingLock:
        raise ScanLockError("another repair process holds the RefreshLibrary lock")

    def __exit__(self, *args: Any) -> None:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _snapshot_dict(
    *,
    task_id: str = "abc12345-def6-7890-abcd-ef1234567890",
    key: str = REFRESH_LIBRARY_KEY,
    state: str = "Idle",
    result: dict[str, Any] | None | object = _SENTINEL,
) -> dict[str, Any]:
    """Build a raw Jellyfin task dict matching scanner expectations."""
    d: dict[str, Any] = {"Id": task_id, "Key": key, "State": state}
    if result is not _SENTINEL:
        d["LastExecutionResult"] = result
    return d


COMPLETED_RESULT = {
    "Status": "Completed",
    "StartTimeUtc": "2026-08-19T10:00:00Z",
    "EndTimeUtc": "2026-08-19T10:05:00Z",
    "ErrorMessage": None,
    "LongErrorMessage": None,
}

FAILED_RESULT = {
    "Status": "Failed",
    "StartTimeUtc": "2026-08-19T10:00:00Z",
    "EndTimeUtc": "2026-08-19T10:05:00Z",
    "ErrorMessage": "disk full",
    "LongErrorMessage": None,
}


# ---------------------------------------------------------------------------
# Mock client factory
# ---------------------------------------------------------------------------

def _make_client(
    *,
    tasks: list[dict[str, Any]] | None = None,
    polled_task: dict[str, Any] | None = None,
    start_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a mock client satisfying ScheduledTaskClient protocol."""
    client = MagicMock()
    if tasks is None:
        tasks = [_snapshot_dict()]
    client.get_scheduled_tasks.return_value = tasks
    if polled_task is not None:
        client.get_scheduled_task.return_value = polled_task
    else:
        client.get_scheduled_task.return_value = tasks[0]
    if start_side_effect is not None:
        client.start_scheduled_task.side_effect = start_side_effect
    else:
        client.start_scheduled_task.return_value = None
    return client


# ===========================================================================
# TestParseExecutionResult
# ===========================================================================


class TestParseExecutionResult(TestCase):
    """Validate parse_execution_result for various input shapes."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(parse_execution_result(None))

    def test_valid_completed_result(self) -> None:
        r = parse_execution_result(COMPLETED_RESULT)
        self.assertIsNotNone(r)
        self.assertEqual(r.status, "Completed")
        self.assertEqual(r.start_time_utc, "2026-08-19T10:00:00Z")
        self.assertEqual(r.end_time_utc, "2026-08-19T10:05:00Z")
        self.assertIsNone(r.error_message)
        self.assertTrue(r.is_completed)

    def test_valid_failed_result(self) -> None:
        r = parse_execution_result(FAILED_RESULT)
        self.assertIsNotNone(r)
        self.assertEqual(r.status, "Failed")
        self.assertFalse(r.is_completed)
        self.assertEqual(r.error_message, "disk full")

    def test_error_text_merges_fields(self) -> None:
        r = parse_execution_result({
            "Status": "Failed",
            "ErrorMessage": "short",
            "LongErrorMessage": "detailed info",
        })
        self.assertIn("short", r.error_text)
        self.assertIn("detailed info", r.error_text)

    def test_error_text_single_field(self) -> None:
        r = parse_execution_result({
            "Status": "Failed",
            "ErrorMessage": "only short",
            "LongErrorMessage": None,
        })
        self.assertEqual(r.error_text, "only short")

    def test_error_text_no_error(self) -> None:
        r = parse_execution_result(COMPLETED_RESULT)
        self.assertIsNone(r.error_text)

    def test_not_a_mapping_raises(self) -> None:
        with self.assertRaises(MalformedExecutionResultError):
            parse_execution_result("not-a-dict")

    def test_missing_status_raises(self) -> None:
        with self.assertRaises(MalformedExecutionResultError):
            parse_execution_result({"StartTimeUtc": "2026-01-01T00:00:00Z"})

    def test_unknown_status_raises(self) -> None:
        with self.assertRaises(MalformedExecutionResultError):
            parse_execution_result({"Status": "UnknownStatus"})

    def test_empty_string_status_raises(self) -> None:
        with self.assertRaises(MalformedExecutionResultError):
            parse_execution_result({"Status": ""})

    def test_signature_differs_between_results(self) -> None:
        r1 = parse_execution_result(COMPLETED_RESULT)
        r2 = parse_execution_result(FAILED_RESULT)
        self.assertNotEqual(r1.signature, r2.signature)

    def test_signature_same_for_identical_results(self) -> None:
        r1 = parse_execution_result(COMPLETED_RESULT)
        r2 = parse_execution_result(COMPLETED_RESULT)
        self.assertEqual(r1.signature, r2.signature)

    def test_snake_case_fields_accepted(self) -> None:
        r = parse_execution_result({
            "status": "Completed",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "end_time_utc": "2026-01-01T00:01:00Z",
            "error_message": None,
            "long_error_message": None,
        })
        self.assertIsNotNone(r)
        self.assertEqual(r.status, "Completed")


# ===========================================================================
# TestIsNewerExecutionResult
# ===========================================================================


class TestIsNewerExecutionResult(TestCase):
    """Compare execution results by timestamp and signature."""

    def test_current_none_is_not_newer(self) -> None:
        prior = parse_execution_result(COMPLETED_RESULT)
        self.assertFalse(is_newer_execution_result(None, prior))

    def test_prior_none_means_current_is_newer(self) -> None:
        current = parse_execution_result(COMPLETED_RESULT)
        self.assertTrue(is_newer_execution_result(current, None))

    def test_same_signature_is_not_newer(self) -> None:
        r = parse_execution_result(COMPLETED_RESULT)
        self.assertFalse(is_newer_execution_result(r, r))

    def test_later_end_time_is_newer(self) -> None:
        earlier = parse_execution_result({
            "Status": "Completed",
            "EndTimeUtc": "2026-08-19T10:00:00Z",
        })
        later = parse_execution_result({
            "Status": "Completed",
            "EndTimeUtc": "2026-08-19T11:00:00Z",
        })
        self.assertTrue(is_newer_execution_result(later, earlier))

    def test_earlier_end_time_is_not_newer(self) -> None:
        earlier = parse_execution_result({
            "Status": "Completed",
            "EndTimeUtc": "2026-08-19T10:00:00Z",
        })
        later = parse_execution_result({
            "Status": "Completed",
            "EndTimeUtc": "2026-08-19T11:00:00Z",
        })
        self.assertFalse(is_newer_execution_result(earlier, later))

    def test_missing_timestamps_different_signatures_is_newer(self) -> None:
        """Without timestamps, a different signature is treated as newer."""
        r1 = parse_execution_result({"Status": "Completed"})
        r2 = parse_execution_result({"Status": "Failed"})
        self.assertTrue(is_newer_execution_result(r2, r1))


# ===========================================================================
# TestDiscoverRefreshLibraryTask
# ===========================================================================


class TestDiscoverRefreshLibraryTask(TestCase):
    """Discover the RefreshLibrary task from a list."""

    def test_exact_key_match(self) -> None:
        client = _make_client(tasks=[_snapshot_dict()])
        snap = discover_refresh_library_task(client)
        self.assertEqual(snap.key, REFRESH_LIBRARY_KEY)
        self.assertEqual(snap.task_id, "abc12345-def6-7890-abcd-ef1234567890")

    def test_no_matching_key_raises(self) -> None:
        client = _make_client(tasks=[_snapshot_dict(key="Backup")])
        with self.assertRaises(TaskDiscoveryError) as ctx:
            discover_refresh_library_task(client)
        self.assertIn("RefreshLibrary", str(ctx.exception))

    def test_duplicate_key_raises(self) -> None:
        t1 = _snapshot_dict(task_id="aaa-bbb")
        t2 = _snapshot_dict(task_id="ccc-ddd")
        client = _make_client(tasks=[t1, t2])
        with self.assertRaises(TaskDiscoveryError) as ctx:
            discover_refresh_library_task(client)
        self.assertIn("duplicate", str(ctx.exception))

    def test_malformed_task_raises(self) -> None:
        client = _make_client(tasks=["not-a-dict"])
        with self.assertRaises(TaskDiscoveryError):
            discover_refresh_library_task(client)

    def test_task_with_none_id_raises(self) -> None:
        bad_task = {"Key": REFRESH_LIBRARY_KEY, "Id": None, "State": "Idle"}
        client = _make_client(tasks=[bad_task])
        with self.assertRaises(TaskDiscoveryError):
            discover_refresh_library_task(client)

    def test_unsupported_state_raises(self) -> None:
        bad_task = _snapshot_dict(state="Deleted")
        client = _make_client(tasks=[bad_task])
        with self.assertRaises(TaskStateError):
            discover_refresh_library_task(client)

    def test_missing_key_field_raises(self) -> None:
        bad_task = {"Id": "abc-123", "State": "Idle"}
        client = _make_client(tasks=[bad_task])
        with self.assertRaises(TaskDiscoveryError):
            discover_refresh_library_task(client)


# ===========================================================================
# TestRefreshLibraryScanner
# ===========================================================================


class TestRefreshLibraryScanner(TestCase):
    """Full lifecycle tests with injectable clock/sleeper/lock."""

    # -- Successful scan: Idle → start → Running → Idle+Completed ----------

    def test_successful_scan(self) -> None:
        """Idle task gets started, transitions through Running, finishes Idle+Completed."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        running = _snapshot_dict(state="Running", result=COMPLETED_RESULT)
        # New result with later timestamp
        new_result = {
            "Status": "Completed",
            "StartTimeUtc": "2026-08-19T10:10:00Z",
            "EndTimeUtc": "2026-08-19T10:15:00Z",
            "ErrorMessage": None,
            "LongErrorMessage": None,
        }
        done = _snapshot_dict(state="Idle", result=new_result)

        # Clock: initial(0), pre-poll check(1), poll1(10), poll2(20)
        clock = _FakeClock([0.0, 1.0, 10.0, 20.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        client = _make_client(tasks=[initial])
        # First get_scheduled_task returns running, second returns done
        client.get_scheduled_task.side_effect = [running, done]

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        outcome = scanner.scan()

        self.assertTrue(outcome.success)
        self.assertTrue(outcome.started)
        self.assertTrue(outcome.observed_running)
        self.assertTrue(outcome.observed_new_result)
        self.assertEqual(outcome.status, "Completed")
        client.start_scheduled_task.assert_called_once()

    # -- Pre-running task refuses start ------------------------------------

    def test_running_task_refuses_start(self) -> None:
        """When the task is already Running, scanner raises TaskStateError."""
        running = _snapshot_dict(state="Running", result=COMPLETED_RESULT)
        client = _make_client(tasks=[running])
        clock = _FakeClock([0.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        with self.assertRaises(TaskStateError):
            scanner.scan()
        client.start_scheduled_task.assert_not_called()

    # -- Failed outcome ----------------------------------------------------

    def test_failed_outcome(self) -> None:
        """Task completes with Status=Failed → ScanTaskFailed."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        running = _snapshot_dict(state="Running", result=COMPLETED_RESULT)
        new_failed = {
            "Status": "Failed",
            "StartTimeUtc": "2026-08-19T10:10:00Z",
            "EndTimeUtc": "2026-08-19T10:12:00Z",
            "ErrorMessage": "disk error",
            "LongErrorMessage": None,
        }
        done = _snapshot_dict(state="Idle", result=new_failed)

        clock = _FakeClock([0.0, 0.0, 0.0, 0.0, 0.0, 100.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        client = _make_client(tasks=[initial])
        client.get_scheduled_task.side_effect = [running, done]

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        with self.assertRaises(ScanTaskFailed) as ctx:
            scanner.scan()
        self.assertIn("Failed", str(ctx.exception))
        self.assertTrue(ctx.exception.observed_running)

    # -- Cancelled outcome -------------------------------------------------

    def test_cancelled_outcome(self) -> None:
        """Task completes with Status=Cancelled → ScanTaskFailed."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        new_cancelled = {
            "Status": "Cancelled",
            "StartTimeUtc": "2026-08-19T10:10:00Z",
            "EndTimeUtc": "2026-08-19T10:12:00Z",
            "ErrorMessage": None,
            "LongErrorMessage": None,
        }
        done = _snapshot_dict(state="Idle", result=new_cancelled)

        clock = _FakeClock([0.0, 0.0, 0.0, 0.0, 0.0, 100.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        client = _make_client(tasks=[initial])
        client.get_scheduled_task.side_effect = [done]

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        with self.assertRaises(ScanTaskFailed):
            scanner.scan()

    # -- Malformed result --------------------------------------------------

    def test_malformed_result_during_poll(self) -> None:
        """Task returns a malformed result object during polling."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        bad = _snapshot_dict(state="Idle", result="not-a-mapping")

        clock = _FakeClock([0.0, 1.0, 10.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        client = _make_client(tasks=[initial])
        client.get_scheduled_task.return_value = bad

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        with self.assertRaises(ScanError):
            scanner.scan()

    # -- Timeout -----------------------------------------------------------

    def test_timeout(self) -> None:
        """Clock expires → ScanTimeoutError."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        running = _snapshot_dict(state="Running", result=COMPLETED_RESULT)

        # Clock: start at 0, deadline = 0+2 = 2, poll at 0+1=1 (< deadline),
        # then clock returns 3 which is >= deadline → timeout
        clock = _FakeClock([0.0, 1.0, 3.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        client = _make_client(tasks=[initial])
        client.get_scheduled_task.return_value = running

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=2.0,
            poll_interval_seconds=0.1,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        with self.assertRaises(ScanTimeoutError) as ctx:
            scanner.scan()
        self.assertIn("did not reach Idle", str(ctx.exception))
        self.assertTrue(ctx.exception.started)

    # -- Held lock ---------------------------------------------------------

    def test_scan_lock_error(self) -> None:
        """Lock acquisition failure → ScanLockError."""
        initial = _snapshot_dict()
        client = _make_client(tasks=[initial])
        clock = _FakeClock([0.0])
        sleeper = _RecordingSleeper()

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=_RejectingLock(),
        )
        with self.assertRaises(ScanLockError):
            scanner.scan()
        client.start_scheduled_task.assert_not_called()

    # -- Start attempted only once per run ---------------------------------

    def test_start_attempted_only_once(self) -> None:
        """Second start within one run raises ScanStartError."""
        initial = _snapshot_dict(state="Idle", result=COMPLETED_RESULT)
        client = _make_client(tasks=[initial])
        clock = _FakeClock([0.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        # Manually call _start_task twice
        scanner._start_task("task-1", None)
        with self.assertRaises(ScanStartError):
            scanner._start_task("task-1", None)

    # -- try_scan returns ScanOutcome on failure ---------------------------

    def test_try_scan_returns_outcome_on_failure(self) -> None:
        """try_scan wraps ScanError into a ScanOutcome instead of raising."""
        running = _snapshot_dict(state="Running", result=COMPLETED_RESULT)
        client = _make_client(tasks=[running])
        clock = _FakeClock([0.0])
        sleeper = _RecordingSleeper()
        lock = _NoopLock()

        scanner = RefreshLibraryScanner(
            client,
            timeout_seconds=100.0,
            poll_interval_seconds=5.0,
            clock=clock,
            sleeper=sleeper,
            lock=lock,
        )
        outcome = scanner.try_scan()
        self.assertFalse(outcome.success)
        self.assertIsInstance(outcome, ScanOutcome)

    # -- Constructor validation --------------------------------------------

    def test_invalid_poll_interval_and_interval_raises(self) -> None:
        client = _make_client()
        with self.assertRaises(ValueError):
            RefreshLibraryScanner(
                client,
                poll_interval=1.0,
                interval=2.0,
            )

    def test_non_positive_timeout_raises(self) -> None:
        client = _make_client()
        with self.assertRaises(ValueError):
            RefreshLibraryScanner(
                client,
                timeout=0.0,
            )


# ===========================================================================
# TestInterProcessLock
# ===========================================================================


class TestInterProcessLock(TestCase):
    """Acquire / release / held properties for InterProcessLock."""

    def test_acquire_and_release(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            lock = InterProcessLock(tmp.name)
            self.assertFalse(lock.held)
            lock.acquire()
            self.assertTrue(lock.held)
            lock.release()
            self.assertFalse(lock.held)

    def test_context_manager(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            lock = InterProcessLock(tmp.name)
            with lock:
                self.assertTrue(lock.held)
            self.assertFalse(lock.held)

    def test_double_acquire_raises(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            lock = InterProcessLock(tmp.name)
            lock.acquire()
            with self.assertRaises(ScanLockError):
                lock.acquire()
            lock.release()

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            InterProcessLock("")

    def test_whitespace_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            InterProcessLock("   ")

    def test_nul_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            InterProcessLock("/tmp\x00lock")

    def test_non_string_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            InterProcessLock(123)

    def test_release_without_acquire_is_noop(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            lock = InterProcessLock(tmp.name)
            lock.release()  # should not raise
            self.assertFalse(lock.held)


if __name__ == "__main__":
    unittest_main()
