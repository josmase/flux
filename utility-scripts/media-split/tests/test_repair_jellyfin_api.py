"""Mocked tests for JellyfinApiClient transport, authentication, and error handling.

Every test uses an injected transport stub — no credentials, network, or live
Jellyfin instance are contacted.  The transport records all outgoing requests so
assertions can verify header content, URL structure, and absence of secret
material in observable outputs.
"""

from __future__ import annotations

import io
import json
import logging
import ssl
import urllib.error
import urllib.parse
from typing import Any
from unittest import main as unittest_main, TestCase

from jellyfin_library_repair.api import (
    JellyfinApiClient,
    JellyfinMutationAmbiguousError,
    JellyfinResponseError,
    JellyfinTransportError,
    JellyfinUnsupportedEndpointError,
    VIRTUAL_FOLDERS_ENDPOINT,
    VIRTUAL_FOLDER_PATHS_ENDPOINT,
    VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT,
)
from jellyfin_library_repair.credentials import JellyfinCredentials
from jellyfin_library_repair.models import (
    LibraryConfig,
    LibraryKind,
    RepairConfig,
)


TOKEN = "fixture-api-token-redacted"
BASE_URL = "https://jellyfin.invalid"


# ---------------------------------------------------------------------------
# Transport stub: records every request and returns pre-configured responses
# ---------------------------------------------------------------------------

class _RecordingTransport:
    """Minimal callable/attribute-based transport that stores all requests."""

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._responses: list[Any] = list(responses or [])
        self._error = error
        self.calls: list[dict[str, Any]] = []

    # The client tries three attribute patterns: .request(), .urlopen(), .open(),
    # then a plain callable.  We implement all three so the client uses
    # ``.request()`` first.
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
        context: Any,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
                "context": context,
            }
        )
        if self._error is not None:
            raise self._error
        if self._responses:
            return self._responses.pop(0)
        return (200, b"null")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.request(
            method=kwargs.get("method", "GET"),
            url=kwargs.get("url", ""),
            headers=kwargs.get("headers", {}),
            body=kwargs.get("body"),
            timeout=kwargs.get("timeout", 60),
            context=kwargs.get("context"),
        )


def _json_response(data: Any, status: int = 200) -> tuple[int, bytes]:
    """Return a (status, body) tuple that the transport returns as-is."""
    return (status, json.dumps(data).encode("utf-8"))


def _client(
    transport: _RecordingTransport | None = None,
    *,
    token: str = TOKEN,
    **kwargs: Any,
) -> JellyfinApiClient:
    """Build a client with a mock transport and a known token."""
    if transport is None:
        transport = _RecordingTransport()
    return JellyfinApiClient(
        BASE_URL,
        token=token,
        transport=transport,
        **kwargs,
    )


class TestMediaBrowserHeaderAuthentication(TestCase):
    """Verify the v10.11.9 MediaBrowser authorization header is present."""

    def test_authorization_header_contains_media_browser_prefix(self) -> None:
        client = _client()
        header = client.authorization_header
        self.assertTrue(header.startswith("MediaBrowser "), header)
        self.assertIn('Client="media-path-repair"', header)
        self.assertIn('Token="' + TOKEN + '"', header)
        self.assertIn('Device="ops"', header)
        self.assertIn('DeviceId="media-path-repair-1"', header)
        self.assertIn('Version="1.0"', header)

    def test_request_sends_media_browser_authorization(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        client.get_virtual_folders()
        self.assertEqual(len(transport.calls), 1)
        sent_headers = transport.calls[0]["headers"]
        auth = sent_headers.get("Authorization", "")
        self.assertIn("MediaBrowser", auth)
        self.assertIn('Token="' + TOKEN + '"', auth)

    def test_authorization_header_not_in_query_string(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        client.get_virtual_folders()
        url = transport.calls[0]["url"]
        parsed = urllib.parse.urlsplit(url)
        self.assertEqual(parsed.query, "", "query string must be empty for this endpoint")
        self.assertNotIn(TOKEN, url, "token must not appear in the URL")

    def test_post_add_path_sends_refresh_library_false(self) -> None:
        transport = _RecordingTransport([(204, b"")])
        client = _client(transport=transport)
        client.add_virtual_folder_path("Movies", "/srv/media/movies/1")
        url = transport.calls[0]["url"]
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qsl(parsed.query)
        self.assertEqual(params, [("refreshLibrary", "false")])

    def test_delete_remove_path_sends_name_path_refresh_false(self) -> None:
        transport = _RecordingTransport([(204, b"")])
        client = _client(transport=transport)
        client.remove_virtual_folder_path("Movies", "/srv/media/movies/legacy")
        url = transport.calls[0]["url"]
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qsl(parsed.query)
        self.assertIn(("name", "Movies"), params)
        self.assertIn(("path", "/srv/media/movies/legacy"), params)
        self.assertIn(("refreshLibrary", "false"), params)


class TestTLSConfigurationBehavior(TestCase):
    """Verify SSL context and TLS-related configuration defaults."""

    def test_default_ssl_context_is_verified(self) -> None:
        client = _client()
        self.assertTrue(client.verify_tls)
        self.assertIsNotNone(client.ssl_context)
        self.assertFalse(client.insecure)

    def test_insecure_mode_creates_unverified_context(self) -> None:
        client = _client(insecure=True)
        self.assertFalse(client.verify_tls)
        self.assertTrue(client.insecure)

    def test_insecure_with_ca_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            _client(insecure=True, ca_file="/nonexistent/ca.pem")

    def test_timeout_defaults_to_sixty(self) -> None:
        client = _client()
        self.assertEqual(client.timeout, 60.0)

    def test_custom_timeout_is_used(self) -> None:
        client = _client(timeout=12.5)
        self.assertEqual(client.timeout, 12.5)
        transport = _RecordingTransport([_json_response([])])
        client_with_transport = _client(transport=transport, timeout=12.5)
        client_with_transport.get_virtual_folders()
        self.assertEqual(transport.calls[0]["timeout"], 12.5)

    def test_ssl_context_propagated_to_transport(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        ctx = ssl.create_default_context()
        client = _client(transport=transport, ssl_context=ctx)
        client.get_virtual_folders()
        self.assertIs(transport.calls[0]["context"], ctx)

    def test_token_and_api_key_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            JellyfinApiClient(
                BASE_URL,
                token="a",
                api_key="b",
                transport=_RecordingTransport(),
            )


class TestNonSuccessStatusHandling(TestCase):
    """Verify error classes and retry semantics for non-2xx responses."""

    def test_400_raises_response_error(self) -> None:
        transport = _RecordingTransport(
            [_json_response({"Message": "bad request"}, 400)]
        )
        client = _client(transport=transport)
        with self.assertRaises(JellyfinResponseError) as ctx:
            client.get_virtual_folders()
        self.assertEqual(ctx.exception.status, 400)

    def test_404_raises_response_error(self) -> None:
        transport = _RecordingTransport(
            [_json_response({"Message": "not found"}, 404)]
        )
        client = _client(transport=transport)
        with self.assertRaises(JellyfinResponseError) as ctx:
            client.get_virtual_folders()
        self.assertEqual(ctx.exception.status, 404)

    def test_500_get_retries_once_then_raises(self) -> None:
        transport = _RecordingTransport([
            _json_response({"Message": "error"}, 500),
            _json_response({"Message": "error again"}, 500),
        ])
        client = _client(transport=transport, read_retries=1, retry_backoff_seconds=0)
        with self.assertRaises(JellyfinResponseError) as ctx:
            client.get_virtual_folders()
        self.assertEqual(ctx.exception.status, 500)
        # Initial attempt + 1 retry = 2 calls
        self.assertEqual(len(transport.calls), 2)

    def test_post_transport_error_raises_ambiguous(self) -> None:
        transport = _RecordingTransport(
            error=urllib.error.URLError("connection refused")
        )
        client = _client(transport=transport)
        with self.assertRaises(JellyfinMutationAmbiguousError):
            client.add_virtual_folder_path("Movies", "/srv/media/movies/1")
        self.assertEqual(transport.calls[0]["method"], "POST")

    def test_get_transport_error_retries_then_raises_transport_error(self) -> None:
        transport = _RecordingTransport(
            error=urllib.error.URLError("connection refused")
        )
        client = _client(transport=transport, read_retries=1, retry_backoff_seconds=0)
        with self.assertRaises(JellyfinTransportError):
            client.get_virtual_folders()


class TestCredentialRedaction(TestCase):
    """Verify the token never appears in error messages or repr."""

    def test_error_message_redacts_token(self) -> None:
        transport = _RecordingTransport(
            [_json_response({"Message": "error details"}, 400)]
        )
        client = _client(transport=transport)
        with self.assertRaises(JellyfinResponseError) as ctx:
            client.get_virtual_folders()
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_unsupported_endpoint_error_redacts_token(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError) as ctx:
            client.request("DELETE", "/Items")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_credentials_repr_never_shows_token(self) -> None:
        creds = JellyfinCredentials(TOKEN)
        self.assertNotIn(TOKEN, repr(creds))
        self.assertNotIn(TOKEN, str(creds))

    def test_client_does_not_log_token(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        log = io.StringIO()
        logger = logging.getLogger("test.redaction")
        logger.addHandler(logging.StreamHandler(log))
        logger.setLevel(logging.DEBUG)
        client = _client(transport=transport, logger=logger)
        client.get_virtual_folders()
        log_text = log.getvalue()
        self.assertNotIn(TOKEN, log_text)

    def test_error_body_text_redacts_token(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        from jellyfin_library_repair.api import _body_text
        raw = f"something {TOKEN} happened".encode("utf-8")
        result = _body_text(raw, (TOKEN,))
        self.assertNotIn(TOKEN, result)
        self.assertIn("<redacted>", result)


class TestNoQueryStringTokenInURLs(TestCase):
    """Ensure the token is never appended to request URLs."""

    def test_get_url_has_no_token(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        client.get_virtual_folders()
        url = transport.calls[0]["url"]
        self.assertNotIn(TOKEN, url)

    def test_post_url_has_no_token(self) -> None:
        transport = _RecordingTransport([(204, b"")])
        client = _client(transport=transport)
        client.add_virtual_folder_path("Movies", "/srv/media/movies/1")
        url = transport.calls[0]["url"]
        self.assertNotIn(TOKEN, url)

    def test_delete_url_has_no_token(self) -> None:
        transport = _RecordingTransport([(204, b"")])
        client = _client(transport=transport)
        client.remove_virtual_folder_path("Movies", "/srv/media/movies/legacy")
        url = transport.calls[0]["url"]
        self.assertNotIn(TOKEN, url)

    def test_token_in_query_raises_value_error(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises((JellyfinUnsupportedEndpointError, ValueError)):
            client.get(VIRTUAL_FOLDERS_ENDPOINT, query={"apikey": TOKEN})

    def test_refreshlibrary_true_rejected_for_path_endpoint(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            client.post(
                VIRTUAL_FOLDER_PATHS_ENDPOINT,
                {"Name": "Movies", "Path": "/srv/media/movies/1"},
                query=[("refreshLibrary", "true")],
            )

    def test_endpoint_rejects_full_url(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            client.request("GET", "https://evil.example.com/steal")


class TestRouteAllowList(TestCase):
    """Verify only the documented v10.11.9 endpoints are reachable."""

    def test_get_virtual_folders_allowed(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        result = client.get(VIRTUAL_FOLDERS_ENDPOINT)
        self.assertEqual(result, [])

    def test_get_scheduled_tasks_allowed(self) -> None:
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        result = client.get("/ScheduledTasks")
        self.assertEqual(result, [])

    def test_delete_items_not_allowed(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            client.delete("/Items")

    def test_delete_items_with_id_not_allowed(self) -> None:
        transport = _RecordingTransport()
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            client.delete("/Items/some-uuid")

    def test_get_path_endpoint_not_allowed(self) -> None:
        """Direct GET /Library/VirtualFolders/Paths is outside the allow-list."""
        transport = _RecordingTransport([_json_response([])])
        client = _client(transport=transport)
        with self.assertRaises(JellyfinUnsupportedEndpointError):
            client.get(VIRTUAL_FOLDER_PATHS_ENDPOINT)

    def test_post_path_update_endpoint_allowed(self) -> None:
        transport = _RecordingTransport([(204, b"")])
        client = _client(transport=transport)
        client.post(
            VIRTUAL_FOLDER_PATH_UPDATE_ENDPOINT,
            {"Name": "Movies", "PathInfo": {"Path": "/srv/media/movies/1"}},
        )
        self.assertEqual(len(transport.calls), 1)


class TestClientFromConfig(TestCase):
    """Verify RepairConfig-based client construction."""

    def test_from_config_resolves_base_url(self) -> None:
        config = RepairConfig(
            base_url=BASE_URL,
            movies=LibraryConfig(
                kind=LibraryKind.MOVIES,
                name="Movies",
                collection_type="movies",
                desired_paths=("/srv/media/movies/1",),
            ),
        )
        transport = _RecordingTransport([_json_response([])])
        client = JellyfinApiClient(config, token=TOKEN, transport=transport)
        self.assertEqual(client.base_url, BASE_URL)
        client.get_virtual_folders()
        self.assertIn(BASE_URL, transport.calls[0]["url"])


if __name__ == "__main__":
    unittest_main()
