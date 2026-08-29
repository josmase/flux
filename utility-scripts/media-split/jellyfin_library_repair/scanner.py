"""Safe, single-run polling for Jellyfin's ``RefreshLibrary`` task.

Jellyfin returns the task's display key and its route identifier as separate
fields.  This module deliberately discovers the task before starting it,
records the previous execution result, and treats a new completed result as
the only successful completion signal.  It never calls the direct library
refresh endpoint.

The public :class:`RefreshLibraryScanner` raises a typed exception for an
operational failure.  :meth:`RefreshLibraryScanner.try_scan` is available to
callers that prefer a structured failure report.  Both paths hold the same
inter-process lock for the complete discovery/start/poll lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
import errno
import fcntl
import math
import os
import re
import time
from types import TracebackType
from typing import Any, Protocol, cast

from .credentials import redact_sensitive


REFRESH_LIBRARY_KEY = "RefreshLibrary"
DEFAULT_SCAN_LOCK_PATH = "/tmp/jellyfin-library-repair-refresh.lock"
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_TASK_STATES = frozenset({"Idle", "Running", "Cancelling"})
_RESULT_STATUSES = frozenset({"Completed", "Failed", "Cancelled", "Aborted"})
_MISSING = object()


class ScheduledTaskClient(Protocol):
    """The scheduled-task portion of :class:`JellyfinApiClient`."""

    def get_scheduled_tasks(self) -> list[Mapping[str, Any]]: ...

    def get_scheduled_task(self, task_id: str) -> Mapping[str, Any]: ...

    def start_scheduled_task(self, task_id: str) -> None: ...


@dataclass(frozen=True)
class ExecutionResult:
    """Validated fields from Jellyfin's ``LastExecutionResult`` object."""

    status: str
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    error_message: str | None = None
    long_error_message: str | None = None

    @property
    def error_text(self) -> str | None:
        """Return available failure text without duplicating both fields."""

        messages = tuple(
            message
            for message in (self.error_message, self.long_error_message)
            if message
        )
        if not messages:
            return None
        return " | ".join(dict.fromkeys(messages))

    @property
    def is_completed(self) -> bool:
        return self.status == "Completed"

    @property
    def signature(self) -> tuple[str, str | None, str | None, str | None, str | None]:
        """Return the result fields used to distinguish executions."""

        return (
            self.status,
            self.start_time_utc,
            self.end_time_utc,
            self.error_message,
            self.long_error_message,
        )


@dataclass(frozen=True)
class ScheduledTaskSnapshot:
    """The safe subset of a discovered or polled Jellyfin task."""

    task_id: str
    key: str
    state: str
    last_execution_result: ExecutionResult | None

    @property
    def id(self) -> str:
        """Compatibility alias for Jellyfin's PascalCase ``Id`` field."""

        return self.task_id

    @property
    def last_result(self) -> ExecutionResult | None:
        return self.last_execution_result


@dataclass(frozen=True)
class ScanOutcome:
    """A successful scan report or a structured report from ``try_scan``."""

    success: bool
    task_id: str | None
    prior_result: ExecutionResult | None
    result: ExecutionResult | None
    state: str | None
    polls: int
    started: bool
    error: str | None = None
    observed_running: bool = False
    observed_new_result: bool = False

    @property
    def completed(self) -> bool:
        return self.success

    @property
    def status(self) -> str | None:
        return self.result.status if self.result is not None else None

    @property
    def error_message(self) -> str | None:
        return self.error


class ScanError(RuntimeError):
    """Base class for failures that must stop the repair run."""

    def __init__(
        self,
        message: str,
        *,
        task_id: str | None = None,
        prior_result: ExecutionResult | None = None,
        result: ExecutionResult | None = None,
        state: str | None = None,
        polls: int = 0,
        started: bool = False,
        observed_running: bool = False,
        observed_new_result: bool = False,
    ) -> None:
        safe_message = redact_sensitive(message)
        self.task_id = task_id
        self.prior_result = prior_result
        self.result = result
        self.state = state
        self.polls = polls
        self.started = started
        self.observed_running = observed_running
        self.observed_new_result = observed_new_result
        self.outcome = ScanOutcome(
            success=False,
            task_id=task_id,
            prior_result=prior_result,
            result=result,
            state=state,
            polls=polls,
            started=started,
            error=safe_message,
            observed_running=observed_running,
            observed_new_result=observed_new_result,
        )
        super().__init__(safe_message)


class ScanLockError(ScanError):
    """Another utility process currently owns the scan lock."""


class TaskDiscoveryError(ScanError):
    """The scheduled-task response could not safely identify RefreshLibrary."""


class TaskStateError(ScanError):
    """The task was not in a state that permits this run to proceed."""


class ScanStartError(ScanError):
    """The one permitted task-start request failed."""


class ScanTaskFailed(ScanError):
    """RefreshLibrary completed with a non-success execution status."""


class ScanTimeoutError(ScanError):
    """The new execution result did not reach a terminal state in time."""


class MalformedExecutionResultError(TaskDiscoveryError):
    """A LastExecutionResult object was not safe to interpret."""


# Descriptive aliases make the failure contract convenient to callers without
# creating separate exception behavior.
RefreshLibraryScanError = ScanError
RefreshLibraryTaskError = ScanTaskFailed
RefreshLibraryTimeoutError = ScanTimeoutError
LockHeldError = ScanLockError


class InterProcessLock(AbstractContextManager["InterProcessLock"]):
    """A non-blocking filesystem lock shared by independent utility processes.

    ``flock`` releases the descriptor automatically if the process exits, so
    an interrupted utility cannot leave a stale ownership marker behind.  The
    lock file contains no PID, token, or other diagnostic data.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        try:
            lock_path = os.fspath(path)
        except TypeError as exc:
            raise ValueError("scan lock path must be filesystem-like") from exc
        if not isinstance(lock_path, str) or not lock_path.strip():
            raise ValueError("scan lock path must be a non-empty path")
        if "\x00" in lock_path:
            raise ValueError("scan lock path must not contain NUL characters")
        self.path = lock_path
        self._handle: Any = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> "InterProcessLock":
        if self._handle is not None:
            raise ScanLockError(f"scan lock is already held by this process: {self.path}")
        try:
            handle = open(self.path, "a+", encoding="ascii")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise ScanLockError("another repair process holds the RefreshLibrary lock") from None
            raise ScanLockError(
                f"unable to acquire RefreshLibrary lock at {self.path}: {type(exc).__name__}"
            ) from None
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass

    def __enter__(self) -> "InterProcessLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()


# A short alias is useful for callers that do not need to distinguish the
# implementation from the serialization guarantee.
ScanLock = InterProcessLock
FileLock = InterProcessLock


def _field(value: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    for name in names:
        if name in value:
            return value[name]
    if default is not _MISSING:
        return default
    raise KeyError(names[0])


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field_name} contains invalid control characters")
    return value


def _task_id(value: Any) -> str:
    identifier = _required_text(value, "scheduled task Id")
    if _TASK_ID.fullmatch(identifier) is None:
        raise ValueError("scheduled task Id contains invalid characters")
    return identifier


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def parse_execution_result(value: Any) -> ExecutionResult | None:
    """Validate one Jellyfin ``LastExecutionResult`` value.

    A missing/null result is valid before the first recorded execution.  Once
    an object is present its status must be one of the documented terminal
    statuses; accepting an unknown value would make completion ambiguous.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MalformedExecutionResultError("LastExecutionResult is not an object")
    try:
        status = _required_text(_field(value, "Status", "status"), "result Status")
        if status not in _RESULT_STATUSES:
            raise ValueError(f"unsupported result Status {status!r}")
        start = _optional_text(
            _field(value, "StartTimeUtc", "start_time_utc", default=None),
            "result StartTimeUtc",
        )
        end = _optional_text(
            _field(value, "EndTimeUtc", "end_time_utc", default=None),
            "result EndTimeUtc",
        )
        error = _optional_text(
            _field(value, "ErrorMessage", "error_message", default=None),
            "result ErrorMessage",
        )
        long_error = _optional_text(
            _field(value, "LongErrorMessage", "long_error_message", default=None),
            "result LongErrorMessage",
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MalformedExecutionResultError):
            raise
        raise MalformedExecutionResultError(f"malformed LastExecutionResult: {exc}") from None
    return ExecutionResult(
        status=status,
        start_time_utc=start,
        end_time_utc=end,
        error_message=error,
        long_error_message=long_error,
    )


def _snapshot(value: Any, *, endpoint: str) -> ScheduledTaskSnapshot:
    if not isinstance(value, Mapping):
        raise TaskDiscoveryError(f"{endpoint} returned a task that is not an object")
    try:
        key = _required_text(_field(value, "Key", "key"), "scheduled task Key")
        identifier = _task_id(_field(value, "Id", "id"))
        state = _required_text(_field(value, "State", "state"), "scheduled task State")
        result = parse_execution_result(
            _field(value, "LastExecutionResult", "last_execution_result", default=None)
        )
    except ScanError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskDiscoveryError(f"{endpoint} returned malformed task data: {exc}") from None
    if state not in _TASK_STATES:
        raise TaskStateError(f"RefreshLibrary task returned unsupported State {state!r}", task_id=identifier)
    return ScheduledTaskSnapshot(
        task_id=identifier,
        key=key,
        state=state,
        last_execution_result=result,
    )


def _client_method(client: Any, names: Sequence[str], endpoint: str) -> Callable[..., Any]:
    for name in names:
        method = getattr(client, name, None)
        if callable(method):
            return cast(Callable[..., Any], method)
    raise TaskDiscoveryError(f"client does not provide the scheduled-task operation {endpoint}")


def _list_tasks(client: Any) -> list[Mapping[str, Any]]:
    method = _client_method(client, ("get_scheduled_tasks", "list_scheduled_tasks"), "GET /ScheduledTasks")
    try:
        payload = method()
    except ScanError:
        raise
    except Exception as exc:
        raise TaskDiscoveryError(
            f"unable to read GET /ScheduledTasks: {type(exc).__name__}: {redact_sensitive(str(exc))}"
        ) from None
    if not isinstance(payload, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in payload
    ):
        raise TaskDiscoveryError("GET /ScheduledTasks returned a malformed task list")
    return list(payload)


def discover_refresh_library_task(client: Any) -> ScheduledTaskSnapshot:
    """Discover the exact ``RefreshLibrary`` task and preserve its Id."""

    tasks = _list_tasks(client)
    matches = [
        item
        for item in tasks
        if _field(item, "Key", "key", default=None) == REFRESH_LIBRARY_KEY
    ]
    if not matches:
        raise TaskDiscoveryError("GET /ScheduledTasks did not return Key RefreshLibrary")
    if len(matches) > 1:
        raise TaskDiscoveryError("GET /ScheduledTasks returned duplicate Key RefreshLibrary tasks")
    return _snapshot(matches[0], endpoint="GET /ScheduledTasks")


# Descriptive aliases for discovery-only callers.
find_refresh_library_task = discover_refresh_library_task
discover_refresh_task = discover_refresh_library_task


def _parse_polled_task(value: Any, task_id: str) -> ScheduledTaskSnapshot:
    snapshot = _snapshot(value, endpoint=f"GET /ScheduledTasks/{task_id}")
    if snapshot.task_id != task_id:
        raise TaskStateError(
            f"GET /ScheduledTasks/{task_id} returned a different task Id {snapshot.task_id!r}",
            task_id=task_id,
        )
    return snapshot


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    candidate = value
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    # System.Text.Json can emit seven fractional digits while datetime accepts
    # six.  Truncation preserves ordering at Python's available precision.
    match = re.match(r"^(.*\.)(\d{7,})([+-].*)$", candidate)
    if match:
        candidate = f"{match.group(1)}{match.group(2)[:6]}{match.group(3)}"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def is_newer_execution_result(
    current: ExecutionResult | None,
    prior: ExecutionResult | None,
) -> bool:
    """Return whether ``current`` can safely represent a later execution."""

    if current is None:
        return False
    if prior is None:
        return True
    if current.signature == prior.signature:
        return False

    for field_name in ("start_time_utc", "end_time_utc"):
        current_value = _parse_timestamp(getattr(current, field_name))
        prior_value = _parse_timestamp(getattr(prior, field_name))
        if current_value is None or prior_value is None:
            continue
        if current_value > prior_value:
            return True
        if current_value < prior_value:
            return False
    # Synthetic fixtures and older captures may omit timestamps.  A changed,
    # otherwise valid result is the only evidence available in that case.
    return True


def _failure_text(result: ExecutionResult) -> str:
    details = result.error_text
    if details:
        return f"RefreshLibrary task ended with Status={result.status}: {details}"
    return f"RefreshLibrary task ended with Status={result.status}"


class RefreshLibraryScanner:
    """Discover, start once, and poll one Jellyfin RefreshLibrary execution."""

    def __init__(
        self,
        client: ScheduledTaskClient | Any,
        *,
        timeout_seconds: float = 1800.0,
        poll_interval_seconds: float = 5.0,
        lock_path: str | os.PathLike[str] = DEFAULT_SCAN_LOCK_PATH,
        lock: AbstractContextManager[Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        timeout: float | None = None,
        poll_interval: float | None = None,
        interval: float | None = None,
        config: Any = None,
    ) -> None:
        if timeout is not None:
            timeout_seconds = timeout
        if poll_interval is not None and interval is not None:
            raise ValueError("poll_interval and interval cannot both be supplied")
        if poll_interval is not None:
            poll_interval_seconds = poll_interval
        elif interval is not None:
            poll_interval_seconds = interval
        if config is not None:
            timeout_seconds = getattr(config, "poll_timeout_seconds", timeout_seconds)
            poll_interval_seconds = getattr(config, "poll_interval", poll_interval_seconds)
        self.client = client
        self.timeout_seconds = self._positive(timeout_seconds, "scan timeout")
        self.poll_interval_seconds = self._non_negative(
            poll_interval_seconds, "poll interval"
        )
        if not callable(clock) or not callable(sleeper):
            raise ValueError("clock and sleeper must be callable")
        self.clock = clock
        self.sleeper = sleeper
        self.lock = lock if lock is not None else InterProcessLock(lock_path)
        self._start_count = 0

    @staticmethod
    def _positive(value: Any, field_name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be positive") from exc
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{field_name} must be positive")
        return number

    @staticmethod
    def _non_negative(value: Any, field_name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be non-negative") from exc
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return number

    def _get_task(self, task_id: str) -> ScheduledTaskSnapshot:
        try:
            method = _client_method(
                self.client,
                ("get_scheduled_task", "get_task"),
                f"GET /ScheduledTasks/{task_id}",
            )
            payload = method(task_id)
        except ScanError:
            raise
        except Exception as exc:
            raise TaskStateError(
                f"unable to read GET /ScheduledTasks/{task_id}: {type(exc).__name__}: "
                f"{redact_sensitive(str(exc))}",
                task_id=task_id,
            ) from None
        try:
            return _parse_polled_task(payload, task_id)
        except ScanError as exc:
            if exc.task_id is None:
                raise TaskStateError(str(exc), task_id=task_id) from None
            raise

    def _start_task(self, task_id: str, prior_result: ExecutionResult | None) -> None:
        if self._start_count:
            raise ScanStartError(
                "RefreshLibrary start was already attempted in this repair run",
                task_id=task_id,
                prior_result=prior_result,
            )
        self._start_count += 1
        try:
            method = _client_method(
                self.client,
                ("start_scheduled_task", "run_scheduled_task", "start_task", "run_task"),
                f"POST /ScheduledTasks/Running/{task_id}",
            )
            method(task_id)
        except ScanError:
            raise
        except Exception as exc:
            raise ScanStartError(
                f"unable to start POST /ScheduledTasks/Running/{task_id}: "
                f"{type(exc).__name__}: {redact_sensitive(str(exc))}",
                task_id=task_id,
                prior_result=prior_result,
                started=False,
            ) from None

    def _max_polls(self) -> int:
        # The clock remains authoritative.  This bound only prevents a broken
        # injected sleeper/clock from turning a failed test or process into a
        # busy infinite loop.
        effective_interval = max(self.poll_interval_seconds, 0.01)
        return max(1, math.ceil(self.timeout_seconds / effective_interval) + 1)

    def _timeout(
        self,
        *,
        task_id: str,
        prior_result: ExecutionResult | None,
        result: ExecutionResult | None,
        state: str | None,
        polls: int,
        observed_running: bool,
        observed_new_result: bool,
    ) -> ScanTimeoutError:
        return ScanTimeoutError(
            f"RefreshLibrary task did not reach Idle with a new execution result "
            f"within {self.timeout_seconds:g} seconds",
            task_id=task_id,
            prior_result=prior_result,
            result=result,
            state=state,
            polls=polls,
            started=True,
            observed_running=observed_running,
            observed_new_result=observed_new_result,
        )

    def _poll(
        self,
        task_id: str,
        prior_result: ExecutionResult | None,
    ) -> ScanOutcome:
        deadline = self.clock() + self.timeout_seconds
        max_polls = self._max_polls()
        polls = 0
        observed_running = False
        observed_new_result = False
        last_state: str | None = None
        last_result: ExecutionResult | None = None

        while polls < max_polls:
            if polls and self.clock() >= deadline:
                raise self._timeout(
                    task_id=task_id,
                    prior_result=prior_result,
                    result=last_result,
                    state=last_state,
                    polls=polls,
                    observed_running=observed_running,
                    observed_new_result=observed_new_result,
                )
            snapshot = self._get_task(task_id)
            polls += 1
            last_state = snapshot.state
            last_result = snapshot.last_execution_result
            if snapshot.state in {"Running", "Cancelling"}:
                observed_running = True
            if is_newer_execution_result(last_result, prior_result):
                observed_new_result = True

            if snapshot.state == "Idle" and observed_new_result and last_result is not None:
                if last_result.status == "Completed":
                    return ScanOutcome(
                        success=True,
                        task_id=task_id,
                        prior_result=prior_result,
                        result=last_result,
                        state=snapshot.state,
                        polls=polls,
                        started=True,
                        observed_running=observed_running,
                        observed_new_result=True,
                    )
                raise ScanTaskFailed(
                    _failure_text(last_result),
                    task_id=task_id,
                    prior_result=prior_result,
                    result=last_result,
                    state=snapshot.state,
                    polls=polls,
                    started=True,
                    observed_running=observed_running,
                    observed_new_result=True,
                )

            if self.clock() >= deadline:
                raise self._timeout(
                    task_id=task_id,
                    prior_result=prior_result,
                    result=last_result,
                    state=last_state,
                    polls=polls,
                    observed_running=observed_running,
                    observed_new_result=observed_new_result,
                )
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise self._timeout(
                    task_id=task_id,
                    prior_result=prior_result,
                    result=last_result,
                    state=last_state,
                    polls=polls,
                    observed_running=observed_running,
                    observed_new_result=observed_new_result,
                )
            delay = min(self.poll_interval_seconds, remaining)
            if delay:
                self.sleeper(delay)

        raise self._timeout(
            task_id=task_id,
            prior_result=prior_result,
            result=last_result,
            state=last_state,
            polls=polls,
            observed_running=observed_running,
            observed_new_result=observed_new_result,
        )

    def _scan_locked(self) -> ScanOutcome:
        discovered = discover_refresh_library_task(self.client)
        if discovered.key != REFRESH_LIBRARY_KEY:
            raise TaskDiscoveryError(
                "discovered task key is not the exact RefreshLibrary key",
                task_id=discovered.task_id,
            )
        if discovered.state != "Idle":
            raise TaskStateError(
                f"RefreshLibrary task is already {discovered.state}; refusing to start another scan",
                task_id=discovered.task_id,
                prior_result=discovered.last_execution_result,
                state=discovered.state,
            )
        prior_result = discovered.last_execution_result
        self._start_task(discovered.task_id, prior_result)
        return self._poll(discovered.task_id, prior_result)

    def scan(self) -> ScanOutcome:
        """Run one guarded scan; expected failures raise :class:`ScanError`."""

        try:
            with self.lock:
                return self._scan_locked()
        except ScanError:
            raise
        except Exception as exc:
            raise ScanError(
                f"RefreshLibrary scan aborted: {type(exc).__name__}: {redact_sensitive(str(exc))}"
            ) from None

    run = scan
    execute = scan

    def try_scan(self) -> ScanOutcome:
        """Run one scan and return a failure report instead of raising it."""

        try:
            return self.scan()
        except ScanError as exc:
            return exc.outcome

    try_run = try_scan
    scan_result = try_scan


def scan_refresh_library(
    client: ScheduledTaskClient | Any,
    *,
    raise_on_failure: bool = False,
    **kwargs: Any,
) -> ScanOutcome:
    """Functional entry point for one guarded RefreshLibrary execution."""

    scanner = RefreshLibraryScanner(client, **kwargs)
    return scanner.scan() if raise_on_failure else scanner.try_scan()


def run_refresh_library_scan(
    client: ScheduledTaskClient | Any,
    **kwargs: Any,
) -> ScanOutcome:
    """Strict functional entry point; failures abort by raising ScanError."""

    return RefreshLibraryScanner(client, **kwargs).scan()


poll_refresh_library = run_refresh_library_scan
run_scan = run_refresh_library_scan


__all__ = [
    "DEFAULT_SCAN_LOCK_PATH",
    "ExecutionResult",
    "FileLock",
    "InterProcessLock",
    "LockHeldError",
    "MalformedExecutionResultError",
    "REFRESH_LIBRARY_KEY",
    "RefreshLibraryScanError",
    "RefreshLibraryScanner",
    "RefreshLibraryTaskError",
    "RefreshLibraryTimeoutError",
    "ScanError",
    "ScanLock",
    "ScanLockError",
    "ScanOutcome",
    "ScanStartError",
    "ScanTaskFailed",
    "ScanTimeoutError",
    "ScheduledTaskClient",
    "ScheduledTaskSnapshot",
    "TaskDiscoveryError",
    "TaskStateError",
    "discover_refresh_library_task",
    "discover_refresh_task",
    "find_refresh_library_task",
    "is_newer_execution_result",
    "poll_refresh_library",
    "parse_execution_result",
    "run_refresh_library_scan",
    "run_scan",
    "scan_refresh_library",
]
