"""Credential resolution for the Jellyfin library repair utility.

Only two sources are supported: an environment variable and an explicitly
identified Kubernetes Secret.  Resolved credentials stay in memory for the
caller; this module does not write files, create Secrets, or print values.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .models import ClusterSecretLookup, CredentialSource, RepairConfig


DEFAULT_API_KEY_ENV = "JELLYFIN_API_KEY"
DEFAULT_KUBECTL_TIMEOUT_SECONDS = 30.0

_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_FIELD = re.compile(
    r"(?ix)"
    r"(\b(?:token|password|passwd|api[\s_-]*key|access[\s_-]*token|authorization)\b\s*[:=]\s*)"
    r"([\"']?)([^\"'\s,};]+)(\2)"
)
_REDACTED = "<redacted>"


def redact_sensitive(value: Any, secrets: tuple[str, ...] = ()) -> str:
    """Return diagnostic text with credential-shaped values replaced.

    Known secret values are replaced first, including values that are not
    labelled in a server response.  The field-name pass covers accidental
    token/password/API-key echoes from a subprocess or HTTP error body.
    """

    text = value if isinstance(value, str) else str(value)
    for secret in sorted(
        {secret for secret in secrets if isinstance(secret, str) and secret},
        key=len,
        reverse=True,
    ):
        text = text.replace(secret, _REDACTED)
    return _SENSITIVE_FIELD.sub(r"\1\2" + _REDACTED + r"\4", text)


class CredentialError(RuntimeError):
    """Raised when a configured credential source cannot be resolved."""

    def __init__(self, message: str, *, secrets: tuple[str, ...] = ()) -> None:
        super().__init__(redact_sensitive(message, secrets))


@dataclass(frozen=True, repr=False, init=False)
class JellyfinCredentials:
    """The in-memory token input shared by every credential provider."""

    token: str

    def __init__(
        self,
        token: str | None = None,
        *,
        api_key: str | None = None,
        access_token: str | None = None,
    ) -> None:
        supplied = [value for value in (token, api_key, access_token) if value is not None]
        if len(supplied) != 1:
            raise CredentialError(
                "provide exactly one Jellyfin token, api_key, or access_token"
            )
        object.__setattr__(self, "token", supplied[0])
        self.__post_init__()

    def __post_init__(self) -> None:
        if not isinstance(self.token, str):
            raise CredentialError("Jellyfin credential value must be text")
        token = self.token.strip()
        if not token:
            raise CredentialError("Jellyfin credential value is empty")
        # Reject header-breaking values before they reach urllib.  The token
        # itself is never included in the validation error.
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in token):
            raise CredentialError("Jellyfin credential contains invalid control characters")
        if any(character in token for character in ('"', "\\", ",")):
            raise CredentialError("Jellyfin credential contains invalid header characters")
        object.__setattr__(self, "token", token)

    @property
    def api_key(self) -> str:
        """Compatibility name for Jellyfin API-key callers.

        The value is intentionally available only to in-memory client code;
        representations and public serialization remain redacted.
        """

        return self.token

    @property
    def access_token(self) -> str:
        """Descriptive alias for the value sent in the MediaBrowser header."""

        return self.token

    @property
    def value(self) -> str:
        """Generic in-memory value alias for credential-aware integrations."""

        return self.token

    def __repr__(self) -> str:
        return "JellyfinCredentials(token=<redacted>)"

    def __str__(self) -> str:
        return "JellyfinCredentials(token=<redacted>)"

    def to_public_dict(self) -> dict[str, bool]:
        """Serialize safe credential metadata without the token value."""

        return {"configured": True}


@dataclass(frozen=True, repr=False)
class EnvironmentCredentialProvider:
    """Resolve a Jellyfin token from one named environment variable."""

    variable: str = DEFAULT_API_KEY_ENV
    environ: Mapping[str, str] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.variable, str) or not _ENVIRONMENT_VARIABLE.fullmatch(
            self.variable
        ):
            raise CredentialError(
                "credential environment variable must be a shell variable name"
            )

    @classmethod
    def from_environment(
        cls,
        variable: str = DEFAULT_API_KEY_ENV,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "EnvironmentCredentialProvider":
        return cls(variable, environ=environ)

    def resolve(self) -> JellyfinCredentials:
        values = os.environ if self.environ is None else self.environ
        value = values.get(self.variable)
        if value is None:
            raise CredentialError(
                f"credential environment variable {self.variable!r} is not set"
            )
        return JellyfinCredentials(value)

    def load(self) -> JellyfinCredentials:
        """Descriptive alias used by programmatic callers."""

        return self.resolve()

    def get(self) -> JellyfinCredentials:
        """Compatibility alias for simple provider interfaces."""

        return self.resolve()


@dataclass(frozen=True, repr=False)
class KubernetesSecretCredentialProvider:
    """Read one key from an explicitly selected Kubernetes Secret.

    The command is executed without a shell and only Secret metadata appears
    in its arguments.  Secret data is decoded in memory and is never copied
    to a file, an environment variable, or a diagnostic message.
    """

    lookup: ClusterSecretLookup
    kubectl: str = "kubectl"
    timeout_seconds: float = DEFAULT_KUBECTL_TIMEOUT_SECONDS
    runner: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.lookup, ClusterSecretLookup):
            raise CredentialError("cluster credential lookup is invalid")
        if not isinstance(self.kubectl, str) or not self.kubectl.strip():
            raise CredentialError("kubectl command is invalid")
        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError):
            raise CredentialError("Kubernetes Secret lookup timeout is invalid") from None
        if timeout <= 0:
            raise CredentialError("Kubernetes Secret lookup timeout must be positive")
        object.__setattr__(self, "timeout_seconds", timeout)

    @classmethod
    def from_lookup(
        cls,
        lookup: ClusterSecretLookup,
        *,
        runner: Callable[..., Any] | None = None,
    ) -> "KubernetesSecretCredentialProvider":
        return cls(lookup, runner=runner)

    def _command(self) -> list[str]:
        return [
            self.kubectl,
            "get",
            "secret",
            self.lookup.name,
            "--namespace",
            self.lookup.namespace,
            "--output=json",
        ]

    def resolve(self) -> JellyfinCredentials:
        command = self._command()
        run = subprocess.run if self.runner is None else self.runner
        try:
            result = run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise CredentialError("timed out reading the Kubernetes Secret") from None
        except (OSError, subprocess.SubprocessError):
            # Do not include exception text: subprocess implementations may
            # echo command output, and Secret output must not escape.
            raise CredentialError("unable to read the Kubernetes Secret") from None
        except Exception:
            # Injected runners are allowed for tests and offline callers.  Do
            # not let an implementation-specific exception echo Secret data.
            raise CredentialError("unable to read the Kubernetes Secret") from None

        return self._credentials_from_result(result)

    def _credentials_from_result(self, result: Any) -> JellyfinCredentials:
        return_code = getattr(result, "returncode", 0)
        if return_code != 0:
            raise CredentialError(
                "kubectl could not read the requested Kubernetes Secret "
                f"({self.lookup.namespace}/{self.lookup.name})"
            )

        raw_output = getattr(result, "stdout", "")
        if isinstance(raw_output, bytes):
            try:
                raw_output = raw_output.decode("utf-8")
            except UnicodeDecodeError:
                raise CredentialError("kubectl returned invalid Secret JSON") from None
        if not isinstance(raw_output, str):
            raise CredentialError("kubectl returned invalid Secret JSON")
        try:
            payload = json.loads(raw_output)
        except (TypeError, json.JSONDecodeError):
            # A caller may inject a kubectl wrapper that already selects the
            # requested data key.  Accept that bounded form as base64 too;
            # the normal command above still uses one JSON Secret lookup.
            return self._decode_base64_value(raw_output)
        if not isinstance(payload, Mapping):
            raise CredentialError("kubectl returned an invalid Secret object")

        secret_value = self._secret_value(payload)
        if secret_value is None:
            raise CredentialError(
                "requested key is missing from the Kubernetes Secret "
                f"({self.lookup.namespace}/{self.lookup.name})"
            )
        encoded, is_string_data = secret_value
        if not isinstance(encoded, str):
            raise CredentialError("Kubernetes Secret data has an invalid value")

        # Kubernetes GET responses expose opaque Secret data as base64.  A
        # stringData branch is accepted only for injected test/dry-run
        # objects; the live API does not return it.
        if is_string_data:
            value = encoded
        else:
            value = self._decode_base64_value(encoded).token
        return JellyfinCredentials(value)

    @staticmethod
    def _decode_base64_value(encoded: str) -> JellyfinCredentials:
        try:
            value = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise CredentialError("Kubernetes Secret data is not valid UTF-8") from None
        return JellyfinCredentials(value)

    def _secret_value(self, payload: Mapping[str, Any]) -> tuple[str, bool] | None:
        data = payload.get("data")
        if isinstance(data, Mapping) and self.lookup.key in data:
            value = data[self.lookup.key]
            return (value, False) if isinstance(value, str) else None
        string_data = payload.get("stringData")
        if isinstance(string_data, Mapping) and self.lookup.key in string_data:
            value = string_data[self.lookup.key]
            return (value, True) if isinstance(value, str) else None
        return None

    def load(self) -> JellyfinCredentials:
        """Descriptive alias used by programmatic callers."""

        return self.resolve()

    def get(self) -> JellyfinCredentials:
        """Compatibility alias for simple provider interfaces."""

        return self.resolve()


def resolve_credentials(
    source: CredentialSource | RepairConfig,
    *,
    environ: Mapping[str, str] | None = None,
    kubectl_runner: Callable[..., Any] | None = None,
) -> JellyfinCredentials:
    """Resolve a model-level credential source into client input."""

    if isinstance(source, RepairConfig):
        source = source.credential_source
    if not isinstance(source, CredentialSource):
        raise CredentialError("credential source is invalid")
    if source.environment_variable is not None:
        return EnvironmentCredentialProvider(
            source.environment_variable, environ=environ
        ).resolve()
    lookup = source.cluster_lookup
    if lookup is None:
        raise CredentialError("credential source is invalid")
    return KubernetesSecretCredentialProvider(lookup, runner=kubectl_runner).resolve()


def credentials_from_environment(
    variable: str = DEFAULT_API_KEY_ENV,
    *,
    environ: Mapping[str, str] | None = None,
) -> JellyfinCredentials:
    """Resolve the configured environment credential source."""

    return EnvironmentCredentialProvider(variable, environ=environ).resolve()


def credentials_from_cluster(
    lookup: ClusterSecretLookup,
    *,
    kubectl_runner: Callable[..., Any] | None = None,
) -> JellyfinCredentials:
    """Resolve an explicitly configured Kubernetes Secret key."""

    return KubernetesSecretCredentialProvider(lookup, runner=kubectl_runner).resolve()


# Clear aliases keep integrations descriptive without creating separate secret
# representations or provider behavior.
Credentials = JellyfinCredentials
EnvironmentCredentials = EnvironmentCredentialProvider
EnvironmentCredentialResolver = EnvironmentCredentialProvider
KubernetesSecretProvider = KubernetesSecretCredentialProvider
KubernetesCredentialProvider = KubernetesSecretCredentialProvider
KubernetesSecretCredentialResolver = KubernetesSecretCredentialProvider
ClusterSecretCredentialProvider = KubernetesSecretCredentialProvider
SecretCredentialProvider = KubernetesSecretCredentialProvider
load_credentials = resolve_credentials
resolve_credential = resolve_credentials
load_credential = resolve_credentials


__all__ = [
    "ClusterSecretCredentialProvider",
    "Credentials",
    "CredentialError",
    "DEFAULT_API_KEY_ENV",
    "EnvironmentCredentialProvider",
    "EnvironmentCredentialResolver",
    "EnvironmentCredentials",
    "JellyfinCredentials",
    "KubernetesSecretCredentialProvider",
    "KubernetesSecretCredentialResolver",
    "KubernetesCredentialProvider",
    "KubernetesSecretProvider",
    "SecretCredentialProvider",
    "credentials_from_cluster",
    "credentials_from_environment",
    "load_credentials",
    "load_credential",
    "redact_sensitive",
    "resolve_credential",
    "resolve_credentials",
]
