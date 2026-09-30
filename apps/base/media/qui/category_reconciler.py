#!/usr/bin/env python3
"""Keep qBittorrent arr categories and AutoTMM settings reconciled."""

from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping


LOG = logging.getLogger("qui-category-reconciler")
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_DOWNLOAD_ROOT = "/mnt/storage/downloads/complete"
DESIRED_PREFERENCES = {
    "auto_tmm_enabled": True,
    "category_changed_tmm_enabled": True,
}


def load_categories(path: str) -> list[str]:
    with open(path, encoding="utf-8") as categories_file:
        categories = [line.strip() for line in categories_file]
    return [category for category in categories if category and not category.startswith("#")]


def desired_paths(categories: Iterable[str], root: str = DEFAULT_DOWNLOAD_ROOT) -> dict[str, str]:
    return {category: f"{root.rstrip('/')}/{category}" for category in categories}


class QbitClient:
    def __init__(self, base_url: str, proxy_key: str, timeout: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.proxy_key = proxy_key
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _request(self, path: str, *, data: Mapping[str, str] | None = None) -> bytes:
        encoded = None
        if data is not None:
            encoded = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}/{path.lstrip('/')}", data=encoded)
        with self.opener.open(request, timeout=self.timeout) as response:
            return response.read()

    def login(self) -> None:
        self._request("api/v2/auth/login", data={"username": "", "password": self.proxy_key})

    def categories(self) -> dict[str, dict[str, object]]:
        return json.loads(self._request("api/v2/torrents/categories"))

    def create_category(self, category: str, save_path: str) -> None:
        self._request(
            "api/v2/torrents/createCategory",
            data={"category": category, "savePath": save_path},
        )

    def edit_category(self, category: str, save_path: str) -> None:
        self._request(
            "api/v2/torrents/editCategory",
            data={"category": category, "savePath": save_path},
        )

    def preferences(self) -> dict[str, object]:
        return json.loads(self._request("api/v2/app/preferences"))

    def set_preferences(self, preferences: Mapping[str, object]) -> None:
        self._request(
            "api/v2/app/setPreferences",
            data={"json": json.dumps(preferences, separators=(",", ":"))},
        )


def reconcile_preferences(client: QbitClient) -> int:
    current = client.preferences()
    changes = {
        name: desired
        for name, desired in DESIRED_PREFERENCES.items()
        if current.get(name) is not desired
    }
    if changes:
        client.set_preferences(changes)
    return len(changes)


def reconcile(client: QbitClient, paths: Mapping[str, str]) -> tuple[int, int]:
    client.login()
    existing = client.categories()
    created = 0
    updated = 0
    for category, save_path in paths.items():
        current = existing.get(category)
        if current is None:
            client.create_category(category, save_path)
            created += 1
        elif current.get("savePath", current.get("save_path")) != save_path:
            client.edit_category(category, save_path)
            updated += 1
    return created, updated


def proxy_base(url_base: str) -> str:
    url_base = url_base.strip().rstrip("/")
    if url_base.startswith("http://") or url_base.startswith("https://"):
        return url_base
    return f"http://127.0.0.1:7476/{url_base.lstrip('/')}"


def reconcile_once() -> None:
    categories_file = os.environ.get("CATEGORIES_FILE", "/etc/qui-reconciler/categories.txt")
    paths = desired_paths(load_categories(categories_file))
    client = QbitClient(proxy_base(os.environ["QUI_PROXY_URL_BASE"]), os.environ["QUI_PROXY_KEY"])
    client.login()
    preference_changes = reconcile_preferences(client)
    created, updated = reconcile(client, paths)
    LOG.info(
        "Reconciled %d categories: created=%d updated=%d preference_changes=%d",
        len(paths),
        created,
        updated,
        preference_changes,
    )


def wait_for_qui() -> None:
    request = urllib.request.Request("http://127.0.0.1:7476/health")
    delay = 2
    while True:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status < 400:
                    return
        except Exception as error:  # noqa: BLE001 - startup dependency is intentionally retried
            LOG.warning("qUI is not ready yet: %s", error.__class__.__name__)
        time.sleep(delay)
        delay = min(delay * 2, 30)


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    interval = max(30, int(os.environ.get("RECONCILE_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    wait_for_qui()
    while True:
        try:
            reconcile_once()
        except Exception as error:  # noqa: BLE001 - keep qUI available and retry on the next cycle
            LOG.error("Category reconciliation failed: %s", error.__class__.__name__)
        time.sleep(interval)


if __name__ == "__main__":
    main()
