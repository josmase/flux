"""Authenticated, version-pinned Jellyfin v10.11.9 API client.

The client deliberately exposes only the library-path, scheduled-task, and
read-only verification routes needed by the repair workflow.  Mutation calls
are single-attempt operations: a timeout or transport failure is reported as
ambiguous and is never retried automatically.
"""

from __future__ import annotations

import json
import logging
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from .credentials import (
    CredentialError,
    JellyfinCredentials,
    redact_sensitive,
    resolve_credentials,
)
from .models import (
    CredentialSource,
    RepairConfig,
    validate_absolute_path,
)


LOGGER = logging.getLogger(__name__)

VIRTUAL_FOLDERS_ENDPOINT = "/Library/VirtualFolders"
VIRTUAL_FOLDER_PATHS_ENDPOINT = "/Library/VirtualFolders/Paths"
VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT = "/Library/VirtualFolders/Paths/Update"
SCHEDULED_TASKS_ENDPOINT = "/ScheduledTasks"
ITEMS_ENDPOINT = "/Items"

_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_DISALLOWED_QUERY_KEY = re.compile(
    r"^(?:api[_-]?key|apikey|token|access[_-]?token|password|authorization|x-api-key)$",
    re.IGNORECASE,
)
_SCHEDULED_TASK_ITEM = re.compile(r"^/ScheduledTasks/[^/]+$")
_SCHEDULED_TASK_RUN = re.compile(r"^/ScheduledTasks/Running/[^/]+$")
_ITEM = re.compile(r"^/Items(?:/[^/]+)?$")


class JellyfinApiError(RuntimeError):
    """Base error with safe method/endpoint context."""

    def __init__(
        self,
        method: str,
        endpoint: str,
        message: str,
        *,
        status: int | None = None,
        attempts: int = 1,
        ambiguous: bool = False,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self.method = method.upper()
        self.endpoint = redact_sensitive(endpoint, secrets)
        self.status = status
        self.attempts = attempts
        self.ambiguous = ambiguous
        safe_message = redact_sensitive(message, secrets)
        super().__init__(self._format_message(safe_message))

    def _format_message(self, message: str) -> str:
        status = f" HTTP {self.status}" if self.status is not None else ""
        return f"{self.method} {self.endpoint}{status}: {message}"


class JellyfinResponseError(JellyfinApiError):
    """Raised for an unexpected HTTP status."""


class JellyfinTransportError(JellyfinApiError):
    """Raised when a request cannot obtain a usable response."""


class JellyfinMutationAmbiguousError(JellyfinTransportError):
    """A POST/DELETE may have reached Jellyfin and therefore is not retried."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ambiguous"] = True
        super().__init__(*args, **kwargs)


class JellyfinSchemaError(JellyfinApiError):
    """Raised when a successful response is not valid JSON or expected data."""


class JellyfinUnsupportedEndpointError(JellyfinApiError):
    """Raised when a caller requests an endpoint outside the safe API surface."""


def _positive_number(value: float, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be a positive number")
    return number


def _non_negative_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if number < 0 or number != value:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return number


def _base_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Jellyfin base URL must be a non-empty URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Jellyfin base URL is malformed") from exc
    del port
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Jellyfin base URL must include an http:// or https:// host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Jellyfin base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Jellyfin base URL must not contain a query or fragment")
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field_name} contains invalid control characters")
    return value


def _response_status(response: Any) -> int | None:
    if isinstance(response, tuple) and len(response) == 2:
        value = response[0]
        try:
            return int(cast(Any, value))
        except (TypeError, ValueError):
            return None
    for attribute in ("status", "status_code"):
        value = getattr(response, attribute, None)
        if value is not None:
            try:
                return int(cast(Any, value))
            except (TypeError, ValueError):
                return None
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        try:
            value = getcode()
            return int(cast(Any, value)) if value is not None else None
        except (TypeError, ValueError, OSError):
            return None
    return None


def _close(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass


def _response_bytes(response: Any) -> bytes:
    if isinstance(response, tuple) and len(response) == 2:
        response = response[1]
    read = getattr(response, "read", None)
    if callable(read):
        value = read()
    else:
        json_method = getattr(response, "json", None)
        if callable(json_method):
            value = json.dumps(json_method()).encode("utf-8")
        else:
            value = response
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return json.dumps(value).encode("utf-8")
    raise TypeError("HTTP response body is not text or bytes")


def _body_text(value: bytes, secrets: tuple[str, ...]) -> str:
    text = value.decode("utf-8", errors="replace").strip()
    if not text:
        return "<empty response>"
    text = redact_sensitive(text, secrets)
    if len(text) > 512:
        text = text[:512] + "..."
    return text


class JellyfinApiClient:
    """Small, injectable HTTP client for the Jellyfin 10.11.9 contract."""

    @classmethod
    def from_config(cls, config: RepairConfig, **kwargs: Any) -> "JellyfinApiClient":
        """Build a client while resolving the model's configured source."""

        return cls(config, **kwargs)

    from_repair_config = from_config

    def __init__(
        self,
        base_url: str | RepairConfig | None = None,
        credentials: JellyfinCredentials | CredentialSource | str | None = None,
        *,
        token: str | None = None,
        api_key: str | None = None,
        config: RepairConfig | None = None,
        credential_source: CredentialSource | None = None,
        timeout: float | None = None,
        request_timeout_seconds: float | None = None,
        ca_file: str | None = None,
        tls_ca_file: str | None = None,
        insecure: bool | None = None,
        transport: Any = None,
        environ: Mapping[str, str] | None = None,
        kubectl_runner: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        read_retries: int = 1,
        max_read_retries: int | None = None,
        retry_backoff_seconds: float = 0.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if token is not None and api_key is not None:
            raise ValueError("token and api_key cannot both be supplied")
        direct_token = token if token is not None else api_key
        if direct_token is not None:
            if credentials is not None or credential_source is not None:
                raise ValueError(
                    "direct token cannot be combined with credential source options"
                )
            credentials = direct_token
        if config is not None:
            if base_url is not None:
                raise ValueError("base_url and config cannot both be supplied")
            base_url = config
        if isinstance(base_url, RepairConfig):
            repair_config = base_url
            base_url = repair_config.base_url
            if credentials is None and credential_source is None:
                credential_source = repair_config.credential_source
            if timeout is None and request_timeout_seconds is None:
                timeout = repair_config.request_timeout_seconds
            if ca_file is None and tls_ca_file is None:
                ca_file = repair_config.tls_ca_file
            if insecure is None:
                insecure = repair_config.insecure
        if base_url is None:
            raise ValueError("Jellyfin base URL is required")
        self.base_url = _base_url(base_url)

        if timeout is not None and request_timeout_seconds is not None:
            raise ValueError("timeout and request_timeout_seconds cannot both be supplied")
        request_timeout = timeout if timeout is not None else request_timeout_seconds
        self.timeout = _positive_number(
            60.0 if request_timeout is None else request_timeout,
            "request timeout",
        )

        if ca_file is not None and tls_ca_file is not None:
            raise ValueError("ca_file and tls_ca_file cannot both be supplied")
        ca_path = ca_file if ca_file is not None else tls_ca_file
        if ca_path is not None:
            ca_path = _text(ca_path, "TLS CA file")
        self.insecure = bool(False if insecure is None else insecure)
        if self.insecure and ca_path is not None:
            raise ValueError("insecure TLS mode cannot be combined with a CA file")
        self.ca_file = ca_path
        self.tls_ca_file = ca_path
        self.ssl_context = (
            ssl_context
            if ssl_context is not None
            else self._build_ssl_context(ca_path, self.insecure)
        )
        self.context = self.ssl_context
        self.tls_context = self.ssl_context

        if credential_source is not None and credentials is not None:
            raise ValueError("credentials and credential_source cannot both be supplied")
        if credential_source is not None:
            credentials = credential_source
        if isinstance(credentials, CredentialSource):
            credentials = resolve_credentials(
                credentials,
                environ=environ,
                kubectl_runner=kubectl_runner,
            )
        elif isinstance(credentials, str):
            credentials = JellyfinCredentials(credentials)
        if not isinstance(credentials, JellyfinCredentials):
            raise CredentialError(
                "Jellyfin credentials are required from an environment or cluster Secret"
            )
        self.credentials = credentials

        retries = read_retries if max_read_retries is None else max_read_retries
        self.read_retries = _non_negative_integer(retries, "read retries")
        self.retry_backoff_seconds = _positive_number(
            retry_backoff_seconds if retry_backoff_seconds else 0.000001,
            "retry backoff",
        )
        # A zero backoff is useful for tests and should remain a real zero at
        # request time; _positive_number above only validates the value.
        if retry_backoff_seconds == 0:
            self.retry_backoff_seconds = 0.0
        self.transport = transport
        self.logger = LOGGER if logger is None else logger
        self.sleeper = sleeper

        if self.insecure:
            warning = (
                "TLS certificate verification is disabled for this Jellyfin client; "
                "use --insecure only for a controlled connection"
            )
            warnings.warn(warning, RuntimeWarning, stacklevel=2)
            self.logger.warning(warning)

    @property
    def token(self) -> str:
        """In-memory token access for request-building integrations."""

        return self.credentials.token

    @property
    def api_key(self) -> str:
        """Compatibility alias for Jellyfin API-key integrations."""

        return self.credentials.token

    @property
    def verify_tls(self) -> bool:
        """Whether certificate verification is enabled for this client."""

        return not self.insecure

    @staticmethod
    def _build_ssl_context(ca_file: str | None, insecure: bool) -> ssl.SSLContext:
        if insecure:
            return ssl._create_unverified_context()
        return ssl.create_default_context(cafile=ca_file)

    @property
    def authorization_header(self) -> str:
        """Return the v10.11.9 MediaBrowser header for the in-memory token."""

        return (
            'MediaBrowser Client="media-path-repair", Device="ops", '
            'DeviceId="media-path-repair-1", Version="1.0", '
            f'Token="{self.credentials.token}"'
        )

    def _query_items(
        self,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None,
    ) -> list[tuple[str, Any]]:
        if query is None:
            return []
        items = list(query.items()) if isinstance(query, Mapping) else list(query)
        normalized: list[tuple[str, Any]] = []
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("Jellyfin query parameters must be key/value pairs")
            key, value = item
            if not isinstance(key, str) or _DISALLOWED_QUERY_KEY.fullmatch(key):
                raise ValueError("credential query parameters are not supported")
            values = value if isinstance(value, (tuple, list)) else (value,)
            for one_value in values:
                if self.credentials.token in str(one_value):
                    raise ValueError("credential values are not allowed in query parameters")
                if key.lower() == "refreshlibrary" and isinstance(one_value, bool):
                    one_value = "true" if one_value else "false"
                normalized.append((key, one_value))
        return normalized

    def _endpoint_parts(
        self,
        endpoint: str,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None,
    ) -> tuple[str, list[tuple[str, Any]]]:
        if not isinstance(endpoint, str):
            raise ValueError("Jellyfin endpoint must be a path")
        try:
            parsed = urllib.parse.urlsplit(endpoint)
            embedded = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        except ValueError as exc:
            raise ValueError("Jellyfin endpoint is malformed") from exc
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError("Jellyfin endpoint must be a relative path")
        path = parsed.path
        decoded_path = urllib.parse.unquote(path)
        encoded_token = urllib.parse.quote(self.credentials.token, safe="")
        if (
            not path.startswith("/")
            or "\\" in path
            or self.credentials.token in path
            or self.credentials.token in decoded_path
            or encoded_token in path
        ):
            raise ValueError("Jellyfin endpoint is not a safe relative path")
        return path, self._query_items(embedded) + self._query_items(query)

    @staticmethod
    def _route_allowed(method: str, path: str) -> bool:
        if method == "GET":
            return path in {
                VIRTUAL_FOLDERS_ENDPOINT,
                SCHEDULED_TASKS_ENDPOINT,
            } or (
                _SCHEDULED_TASK_ITEM.fullmatch(path) is not None
                and not _SCHEDULED_TASK_RUN.fullmatch(path)
                and path.rsplit("/", 1)[-1] != "Running"
            ) or _ITEM.fullmatch(path) is not None
        if method == "POST":
            return path in {
                VIRTUAL_FOLDER_PATHS_ENDPOINT,
                VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT,
            } or _SCHEDULED_TASK_RUN.fullmatch(path) is not None
        if method == "DELETE":
            return path == VIRTUAL_FOLDER_PATHS_ENDPOINT
        return False

    def _url(self, path: str, query: Sequence[tuple[str, Any]]) -> str:
        base = urllib.parse.urlsplit(self.base_url)
        combined_path = f"{base.path.rstrip('/')}{path}"
        encoded_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunsplit(
            (base.scheme, base.netloc, combined_path, encoded_query, "")
        )

    def _request_object(
        self,
        method: str,
        url: str,
        body: bytes | None,
    ) -> urllib.request.Request:
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("Authorization", self.authorization_header)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        return request

    def _open(
        self,
        request: urllib.request.Request,
        method: str,
        url: str,
        body: bytes | None,
    ) -> Any:
        if self.transport is None:
            return urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self.ssl_context,
            )
        if hasattr(self.transport, "request") and callable(self.transport.request):
            return self.transport.request(
                method=method,
                url=url,
                headers=dict(request.header_items()),
                body=body,
                timeout=self.timeout,
                context=self.ssl_context,
            )
        opener = getattr(self.transport, "urlopen", None)
        if callable(opener):
            return opener(request, timeout=self.timeout, context=self.ssl_context)
        opener = getattr(self.transport, "open", None)
        if callable(opener):
            return opener(request, timeout=self.timeout, context=self.ssl_context)
        if callable(self.transport):
            return self.transport(request, timeout=self.timeout, context=self.ssl_context)
        raise TypeError("transport must be urlopen-compatible")

    def _safe_endpoint(self, path: str, query: Sequence[tuple[str, Any]]) -> str:
        # Include only the route in errors/logs.  Query values contain media
        # paths and library names, but omitting them makes credential leakage
        # through an unexpected diagnostic impossible.
        del query
        return path

    @staticmethod
    def _validate_route_query(
        method: str,
        path: str,
        query: Sequence[tuple[str, Any]],
    ) -> None:
        refresh_values = [
            str(value).lower()
            for key, value in query
            if key.lower() == "refreshlibrary"
        ]
        if path == VIRTUAL_FOLDER_PATHS_ENDPOINT and method in {"POST", "DELETE"}:
            if refresh_values != ["false"]:
                raise ValueError(
                    "library path mutations require refreshLibrary=false"
                )
        if path == VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT and refresh_values:
            raise ValueError("path update does not accept refreshLibrary")

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        expected_status: Sequence[int] = (200,),
        json_response: bool = True,
    ) -> Any:
        method = method.upper()
        if method not in {"GET", "POST", "DELETE"}:
            raise JellyfinUnsupportedEndpointError(
                method,
                "<unsupported>",
                "only GET, POST, and DELETE are available",
                secrets=(self.credentials.token,),
            )
        try:
            path, query_items = self._endpoint_parts(endpoint, query)
        except ValueError as exc:
            raise JellyfinUnsupportedEndpointError(
                method,
                "<invalid-endpoint>",
                str(exc),
                secrets=(self.credentials.token,),
            ) from None
        safe_endpoint = self._safe_endpoint(path, query_items)
        if not self._route_allowed(method, path):
            raise JellyfinUnsupportedEndpointError(
                method,
                safe_endpoint,
                "endpoint is outside the v10.11.9 repair API surface",
                secrets=(self.credentials.token,),
            )
        try:
            self._validate_route_query(method, path, query_items)
        except ValueError as exc:
            raise JellyfinUnsupportedEndpointError(
                method,
                safe_endpoint,
                str(exc),
                secrets=(self.credentials.token,),
            ) from None

        try:
            expected = tuple(int(status) for status in expected_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected HTTP statuses are invalid") from exc
        if not expected:
            raise ValueError("at least one expected HTTP status is required")

        request_body: bytes | None = None
        if body is not None:
            try:
                request_body = json.dumps(
                    body, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            except (TypeError, ValueError, UnicodeEncodeError):
                raise JellyfinSchemaError(
                    method,
                    safe_endpoint,
                    "request body is not JSON serializable",
                    secrets=(self.credentials.token,),
                ) from None

        attempts_allowed = 1 + self.read_retries if method == "GET" else 1
        for attempt in range(1, attempts_allowed + 1):
            request_url = self._url(path, query_items)
            request = self._request_object(method, request_url, request_body)
            try:
                response = self._open(request, method, request_url, request_body)
                status = _response_status(response)
                raw_body = _response_bytes(response)
                _close(response)
            except urllib.error.HTTPError as exc:
                status = int(exc.code) if exc.code is not None else None
                try:
                    raw_body = _response_bytes(exc)
                except Exception:
                    raw_body = b""
                _close(exc)
            except Exception as exc:
                if method == "GET" and attempt < attempts_allowed:
                    self._retry_delay(attempt)
                    continue
                error_type = type(exc).__name__
                message = (
                    f"transport failure ({error_type}); "
                    + (
                        "safe read retries exhausted"
                        if method == "GET"
                        else "mutation outcome is ambiguous and was not retried"
                    )
                )
                error_class = (
                    JellyfinTransportError
                    if method == "GET"
                    else JellyfinMutationAmbiguousError
                )
                raise error_class(
                    method,
                    safe_endpoint,
                    message,
                    attempts=attempt,
                    secrets=(self.credentials.token,),
                ) from None

            if status not in expected:
                if method == "GET" and status is not None and status >= 500:
                    if attempt < attempts_allowed:
                        self._retry_delay(attempt)
                        continue
                detail = _body_text(raw_body, (self.credentials.token,))
                raise JellyfinResponseError(
                    method,
                    safe_endpoint,
                    f"unexpected response ({detail})",
                    status=status,
                    attempts=attempt,
                    secrets=(self.credentials.token,),
                )

            if not json_response:
                return None
            if not raw_body:
                raise JellyfinSchemaError(
                    method,
                    safe_endpoint,
                    "successful response did not contain JSON",
                    status=status,
                    attempts=attempt,
                    secrets=(self.credentials.token,),
                )
            try:
                return json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                raise JellyfinSchemaError(
                    method,
                    safe_endpoint,
                    "successful response contained invalid JSON",
                    status=status,
                    attempts=attempt,
                    secrets=(self.credentials.token,),
                ) from None
        raise AssertionError("request loop exhausted without a result")

    def _retry_delay(self, attempt: int) -> None:
        del attempt
        if self.retry_backoff_seconds:
            self.sleeper(self.retry_backoff_seconds)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        expected_status: Sequence[int] | int = (200,),
        json_response: bool = True,
    ) -> Any:
        """Dispatch one allow-listed request without exposing raw transport."""

        expected = (
            (expected_status,)
            if isinstance(expected_status, int)
            else expected_status
        )
        return self._request(
            method,
            endpoint,
            body=body,
            query=query,
            expected_status=expected,
            json_response=json_response,
        )

    def get(
        self,
        endpoint: str,
        *,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        expected_status: Sequence[int] | int = (200,),
        json_response: bool = True,
    ) -> Any:
        if query is not None and params is not None:
            raise ValueError("query and params cannot both be supplied")
        return self.request(
            "GET",
            endpoint,
            query=query if query is not None else params,
            expected_status=expected_status,
            json_response=json_response,
        )

    def post(
        self,
        endpoint: str,
        body: Any = None,
        *,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        expected_status: Sequence[int] | int = (204,),
        json_response: bool = False,
    ) -> Any:
        if query is not None and params is not None:
            raise ValueError("query and params cannot both be supplied")
        return self.request(
            "POST",
            endpoint,
            body=body,
            query=query if query is not None else params,
            expected_status=expected_status,
            json_response=json_response,
        )

    def delete(
        self,
        endpoint: str,
        *,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        expected_status: Sequence[int] | int = (204,),
        json_response: bool = False,
    ) -> Any:
        if query is not None and params is not None:
            raise ValueError("query and params cannot both be supplied")
        return self.request(
            "DELETE",
            endpoint,
            query=query if query is not None else params,
            expected_status=expected_status,
            json_response=json_response,
        )

    def get_virtual_folders(self) -> list[Mapping[str, Any]]:
        payload = self.get(VIRTUAL_FOLDERS_ENDPOINT)
        if not isinstance(payload, list) or any(
            not isinstance(item, Mapping) for item in payload
        ):
            raise JellyfinSchemaError(
                "GET",
                VIRTUAL_FOLDERS_ENDPOINT,
                "response was not a virtual-folder array",
                secrets=(self.credentials.token,),
            )
        return payload

    def list_virtual_folders(self) -> list[Mapping[str, Any]]:
        return self.get_virtual_folders()

    virtual_folders = get_virtual_folders

    def add_virtual_folder_path(self, library_name: str, path: str) -> None:
        name = _text(library_name, "library name")
        location = validate_absolute_path(path, "library path")
        self.post(
            VIRTUAL_FOLDER_PATHS_ENDPOINT,
            {"Name": name, "Path": location},
            query=[("refreshLibrary", "false")],
        )

    def add_library_path(self, library_name: str, path: str) -> None:
        self.add_virtual_folder_path(library_name, path)

    add_path = add_virtual_folder_path

    def remove_virtual_folder_path(self, library_name: str, path: str) -> None:
        name = _text(library_name, "library name")
        location = validate_absolute_path(path, "library path")
        self.delete(
            VIRTUAL_FOLDER_PATHS_ENDPOINT,
            query=[
                ("name", name),
                ("path", location),
                ("refreshLibrary", "false"),
            ],
        )

    def remove_library_path(self, library_name: str, path: str) -> None:
        self.remove_virtual_folder_path(library_name, path)

    remove_path = remove_virtual_folder_path

    def update_virtual_folder_path(self, library_name: str, path: str) -> None:
        name = _text(library_name, "library name")
        location = validate_absolute_path(path, "library path")
        self.post(
            VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT,
            {"Name": name, "PathInfo": {"Path": location}},
        )

    def get_scheduled_tasks(self) -> list[Mapping[str, Any]]:
        payload = self.get(SCHEDULED_TASKS_ENDPOINT)
        if not isinstance(payload, list) or any(
            not isinstance(item, Mapping) for item in payload
        ):
            raise JellyfinSchemaError(
                "GET",
                SCHEDULED_TASKS_ENDPOINT,
                "response was not a scheduled-task array",
                secrets=(self.credentials.token,),
            )
        return payload

    def list_scheduled_tasks(self) -> list[Mapping[str, Any]]:
        return self.get_scheduled_tasks()

    scheduled_tasks = get_scheduled_tasks
    get_tasks = get_scheduled_tasks

    def get_scheduled_task(self, task_id: str) -> Mapping[str, Any]:
        identifier = self._task_id(task_id)
        endpoint = f"{SCHEDULED_TASKS_ENDPOINT}/{urllib.parse.quote(identifier, safe='')}"
        payload = self.get(endpoint)
        if not isinstance(payload, Mapping):
            raise JellyfinSchemaError(
                "GET",
                endpoint,
                "response was not a scheduled-task object",
                secrets=(self.credentials.token,),
            )
        return payload

    get_task = get_scheduled_task

    def start_scheduled_task(self, task_id: str) -> None:
        identifier = self._task_id(task_id)
        endpoint = (
            f"{SCHEDULED_TASKS_ENDPOINT}/Running/"
            f"{urllib.parse.quote(identifier, safe='')}"
        )
        self.post(endpoint)

    def run_scheduled_task(self, task_id: str) -> None:
        self.start_scheduled_task(task_id)

    start_task = start_scheduled_task
    run_task = start_scheduled_task

    @staticmethod
    def _task_id(task_id: str) -> str:
        identifier = _text(task_id, "scheduled task id")
        if _TASK_ID.fullmatch(identifier) is None:
            raise ValueError("scheduled task id contains invalid characters")
        return identifier

    def get_items(
        self,
        *,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        if query is not None and params is not None:
            raise ValueError("query and params cannot both be supplied")
        payload = self.get(ITEMS_ENDPOINT, query=query if query is not None else params)
        if not isinstance(payload, (Mapping, list)):
            raise JellyfinSchemaError(
                "GET",
                ITEMS_ENDPOINT,
                "response was not a Jellyfin item result",
                secrets=(self.credentials.token,),
            )
        return payload

    def list_items(
        self,
        *,
        query: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        return self.get_items(query=query)


# Descriptive aliases for callers that use API rather than client terminology.
JellyfinAPI = JellyfinApiClient
JellyfinAPIClient = JellyfinApiClient
JellyfinApi = JellyfinApiClient
JellyfinClient = JellyfinApiClient
ApiError = JellyfinApiError
HTTPError = JellyfinResponseError
TransportError = JellyfinTransportError
MutationAmbiguousError = JellyfinMutationAmbiguousError
SchemaError = JellyfinSchemaError


__all__ = [
    "ApiError",
    "CredentialError",
    "HTTPError",
    "ITEMS_ENDPOINT",
    "JellyfinAPI",
    "JellyfinAPIClient",
    "JellyfinApi",
    "JellyfinApiClient",
    "JellyfinApiError",
    "JellyfinClient",
    "JellyfinMutationAmbiguousError",
    "JellyfinResponseError",
    "JellyfinSchemaError",
    "JellyfinTransportError",
    "JellyfinUnsupportedEndpointError",
    "MutationAmbiguousError",
    "SCHEDULED_TASKS_ENDPOINT",
    "SchemaError",
    "TransportError",
    "VIRTUAL_FOLDER_PATHS_ENDPOINT",
    "VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT",
    "VIRTUAL_FOLDERS_ENDPOINT",
]
