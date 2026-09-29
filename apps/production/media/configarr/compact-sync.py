#!/usr/bin/env python3
"""Apply the Compact profile to tagged Radarr movies and safely compact files.

The controller deliberately uses only Radarr's v3 API and the shared media
mount.  Radarr performs the download/import; this process only removes an old
path after Radarr reports a different, verified movie file below the limit.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TAG_LABEL = os.getenv("COMPACT_TAG", "compact-candidate")
PROFILE_NAME = os.getenv("COMPACT_PROFILE_NAME", "Compact")
MAX_FILE_BYTES = int(os.getenv("COMPACT_MAX_BYTES", str(4 * 1024**3)))
POLL_SECONDS = int(os.getenv("COMPACT_POLL_SECONDS", "30"))
POLL_TIMEOUT_SECONDS = int(os.getenv("COMPACT_POLL_TIMEOUT_SECONDS", "1800"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "/mnt/storage")).resolve()
RADARR_COUNT = int(os.getenv("RADARR_COUNT", "12"))


def log(message: str) -> None:
    print(message, flush=True)


class ApiError(RuntimeError):
    pass


class Radarr:
    def __init__(self, name: str, base_url: str, api_key: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/api/v3/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ApiError(f"{self.name} {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{self.name} {method} {path}: {exc.reason}") from exc


@dataclass
class MovieState:
    movie: dict[str, Any]
    original_file_id: int | None
    original_path: str | None
    original_size: int


def tagged(movie: dict[str, Any], tag_id: int) -> bool:
    return tag_id in movie.get("tags", [])


def file_info(movie: dict[str, Any]) -> tuple[int | None, str | None, int]:
    movie_file = movie.get("movieFile") or {}
    return (
        movie_file.get("id"),
        movie_file.get("path"),
        int(movie_file.get("size") or 0),
    )


def safe_path(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(STORAGE_ROOT)
    except ValueError:
        return None
    return candidate


def profile_for(radarr: Radarr) -> dict[str, Any]:
    profiles = radarr.request("GET", "qualityprofile")
    for profile in profiles:
        if profile.get("name") == PROFILE_NAME:
            return profile

    # The profile was previously created manually.  If a new instance is
    # added, clone the repository's normal HD profile rather than guessing
    # quality IDs, which differ between Radarr databases.
    source = next((p for p in profiles if p.get("name") == "HD - 720p/1080p"), None)
    if source is None:
        raise ApiError(f"{radarr.name}: profile {PROFILE_NAME!r} is missing and no HD fallback exists")
    created = copy.deepcopy(source)
    created.pop("id", None)
    created["name"] = PROFILE_NAME
    created["upgradeAllowed"] = True
    if DRY_RUN:
        log(f"{radarr.name}: would create profile {PROFILE_NAME!r} from {source['name']!r}")
        return {**created, "id": -1}
    return radarr.request("POST", "qualityprofile", created)


def update_movie_profile(radarr: Radarr, movie: dict[str, Any], profile_id: int) -> bool:
    if movie.get("qualityProfileId") == profile_id:
        return False
    changed = copy.deepcopy(movie)
    changed["qualityProfileId"] = profile_id
    changed.pop("movieFile", None)
    if DRY_RUN:
        log(f"{radarr.name}: would assign Compact to {movie.get('title')} ({movie['id']})")
    else:
        radarr.request("PUT", f"movie/{movie['id']}", changed)
    return True


def queued_for_movie(radarr: Radarr, movie_id: int) -> bool:
    queue = radarr.request("GET", "queue", query={"movieId": movie_id, "pageSize": 100})
    return any(item.get("movieId") == movie_id for item in queue.get("records", []))


def search_movie(radarr: Radarr, movie_id: int, title: str) -> bool:
    if queued_for_movie(radarr, movie_id):
        log(f"{radarr.name}: {title}: search already has a queued item")
        return False
    command = {"name": "MoviesSearch", "movieIds": [movie_id], "sendUpdatesToClient": False}
    if DRY_RUN:
        log(f"{radarr.name}: would search {title} ({movie_id})")
    else:
        radarr.request("POST", "command", command)
    return True


def wait_for_compact_file(radarr: Radarr, state: MovieState) -> tuple[dict[str, Any] | None, bool]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        current = radarr.request("GET", f"movie/{state.movie['id']}", query={"includeMovieFile": "true"})
        file_id, path, size = file_info(current)
        if file_id and path and size <= MAX_FILE_BYTES:
            if file_id != state.original_file_id or path != state.original_path or size < state.original_size:
                return current, True
        time.sleep(POLL_SECONDS)
    return None, False


def remove_old_path(state: MovieState, current: dict[str, Any]) -> bool:
    old = safe_path(state.original_path)
    new = safe_path(file_info(current)[1])
    if old is None or new is None or old == new or not old.exists():
        return False
    if DRY_RUN:
        log(f"would remove old file after replacement: {old}")
        return True
    old.unlink()
    log(f"removed old file after verified replacement: {old}")
    return True


def process_radarr(radarr: Radarr) -> dict[str, int]:
    counts = {"tagged": 0, "assigned": 0, "searched": 0, "replaced": 0, "failed": 0}
    tag_rows = radarr.request("GET", "tag")
    tag = next((row for row in tag_rows if row.get("label") == TAG_LABEL), None)
    if tag is None:
        log(f"{radarr.name}: tag {TAG_LABEL!r} does not exist; nothing to do")
        return counts

    profile = profile_for(radarr)
    profile_id = int(profile["id"])
    movies = radarr.request("GET", "movie", query={"includeMovieFile": "true"})
    for movie in movies:
        if not tagged(movie, int(tag["id"])):
            continue
        counts["tagged"] += 1
        try:
            if update_movie_profile(radarr, movie, profile_id):
                counts["assigned"] += 1
            original_id, original_path, original_size = file_info(movie)
            state = MovieState(movie, original_id, original_path, original_size)
            if original_id is None:
                if search_movie(radarr, movie["id"], movie.get("title", str(movie["id"]))):
                    counts["searched"] += 1
                continue
            if original_size <= MAX_FILE_BYTES:
                continue
            if search_movie(radarr, movie["id"], movie.get("title", str(movie["id"]))):
                counts["searched"] += 1
            if DRY_RUN:
                continue
            replacement, verified = wait_for_compact_file(radarr, state)
            if not verified or replacement is None:
                log(f"{radarr.name}: {movie.get('title')}: no verified compact replacement yet")
                continue
            if remove_old_path(state, replacement):
                counts["replaced"] += 1
        except (ApiError, OSError, ValueError) as exc:
            counts["failed"] += 1
            log(f"{radarr.name}: {movie.get('title', movie.get('id'))}: {exc}")
    return counts


def main() -> int:
    total = {"tagged": 0, "assigned": 0, "searched": 0, "replaced": 0, "failed": 0}
    log(f"compact sync: tag={TAG_LABEL!r} max_bytes={MAX_FILE_BYTES} dry_run={DRY_RUN}")
    for index in range(1, RADARR_COUNT + 1):
        key = os.getenv(f"RADARR_{index}_API_KEY")
        if not key:
            log(f"radarr-{index}: missing API key")
            total["failed"] += 1
            continue
        radarr = Radarr(
            f"radarr-{index}",
            os.getenv("RADARR_URL_TEMPLATE", "http://radarr-{index}-radarr.media.svc.cluster.local:7878").format(index=index),
            key,
        )
        try:
            counts = process_radarr(radarr)
            for name, value in counts.items():
                total[name] += value
            log(f"{radarr.name}: {counts}")
        except ApiError as exc:
            total["failed"] += 1
            log(str(exc))
    log(f"compact sync total: {total}")
    return 1 if total["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
