#!/usr/bin/env python3
"""Inventory and queue Tdarr AV1 groups in savings-per-CPU-hour order.

The inventory is deliberately independent of Tdarr.  The queue command only
queues paths present in the selected inventory group and requires --execute.
That makes the default invocation read-only and prevents an accidental full
library requeue.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ROOTS = [
    "/mnt/storage/files/movies",
    "/mnt/storage/files/series",
]
VIDEO_EXTENSIONS = {
    ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
    ".mpg", ".ts", ".webm", ".wmv",
}
LEGACY_CODECS = {"h264", "avc1", "vc1", "vp9"}


def ffprobe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-of", "json", "-show_format", "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return {"probe_error": str(exc)}


def first_stream(probe: dict[str, Any], codec_type: str) -> dict[str, Any]:
    return next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == codec_type),
        {},
    )


def has_hdr(probe: dict[str, Any]) -> bool:
    video = first_stream(probe, "video")
    transfer = str(video.get("color_transfer", "")).lower()
    primaries = str(video.get("color_primaries", "")).lower()
    side_data = json.dumps(video.get("side_data_list", [])).lower()
    return transfer in {"smpte2084", "arib-std-b67"} or primaries in {"bt2020", "bt2020nc"} or "dolby vision" in side_data or "dovi" in side_data


def resolution_group(height: int) -> str:
    if height >= 1800:
        return "2160p"
    if height >= 900:
        return "1080p"
    if height >= 500:
        return "720p"
    return "sd"


def classify(codec: str, resolution: str, hdr: bool) -> str:
    if codec in {"av1", "av01"}:
        return "skip-av1"
    if hdr:
        return "deferred-hdr"
    if codec in LEGACY_CODECS:
        return f"legacy-{resolution}"
    if codec in {"hevc", "h265"}:
        return f"hevc-{resolution}"
    return "deferred-unsupported"


def expected_ratio(codec: str) -> float:
    if codec in {"h264", "avc1", "vc1"}:
        return 0.40
    if codec == "vp9":
        return 0.55
    if codec in {"hevc", "h265"}:
        return 0.70
    return 1.0


def cost_factor(resolution: str) -> float:
    return {"sd": 0.25, "720p": 0.45, "1080p": 1.0, "2160p": 4.0}.get(resolution, 1.0)


def record(path: Path, roots: list[Path]) -> dict[str, Any]:
    probe = ffprobe(path)
    video = first_stream(probe, "video")
    codec = str(video.get("codec_name", "unknown")).lower()
    height = int(video.get("height") or 0)
    resolution = resolution_group(height)
    hdr = has_hdr(probe)
    size = path.stat().st_size
    duration = float((probe.get("format") or {}).get("duration") or 0)
    group = classify(codec, resolution, hdr)
    expected_saved = size * (1.0 - expected_ratio(codec))
    cost = max(duration, 1.0) * cost_factor(resolution)
    relative = next((str(path.relative_to(root)) for root in roots if path.is_relative_to(root)), str(path))
    return {
        "path": str(path),
        "relative_path": relative,
        "size_bytes": size,
        "duration_seconds": duration,
        "codec": codec,
        "height": height,
        "resolution": resolution,
        "hdr": hdr,
        "group": group,
        "expected_saved_bytes": round(expected_saved),
        "priority": round(expected_saved / cost, 4),
        "probe_error": probe.get("probe_error"),
    }


def inventory(roots: list[Path]) -> list[dict[str, Any]]:
    files = sorted(
        path for root in roots if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
    return [record(path, roots) for path in files]


def api_call(base_url: str, api_key: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method="POST" if body is not None else "GET",
        headers={"x-api-key": api_key, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Tdarr API request failed: {exc}") from exc


def tdarr_files(base_url: str, api_key: str) -> list[dict[str, Any]]:
    result = api_call(
        base_url,
        api_key,
        "/api/v2/cruddb",
        {"data": {"collection": "FileJSONDB", "mode": "getAll"}},
    )
    return result if isinstance(result, list) else []


def queue_group(args: argparse.Namespace, records: list[dict[str, Any]]) -> int:
    if args.group not in {item["group"] for item in records}:
        raise RuntimeError(f"group not present in inventory: {args.group}")
    by_path = {item["path"]: item for item in records if item["group"] == args.group}
    api_key = os.environ.get("TDARR_API_KEY")
    if not api_key:
        raise RuntimeError("TDARR_API_KEY must be set for queue mode")
    files = tdarr_files(args.tdarr_url, api_key)
    tdarr_by_path = {item.get("_id"): item for item in files}
    candidates = []
    for path, item in by_path.items():
        tdarr_path = path.replace(args.media_root, args.tdarr_media_root, 1)
        db_item = tdarr_by_path.get(tdarr_path)
        if not db_item:
            continue
        if db_item.get("TranscodeDecisionMaker") == "Transcode success":
            continue
        candidates.append((item["priority"], db_item["_id"], path))
    candidates.sort(reverse=True)
    print(f"group={args.group} candidates={len(candidates)} batch_size={args.batch_size}")
    for _, _, path in candidates[: args.batch_size]:
        print(path)
    if not args.execute:
        print("dry-run: pass --execute to queue files")
        return 0
    ids = [file_id for _, file_id, _ in candidates[: args.batch_size]]
    if ids:
        api_call(
            args.tdarr_url,
            api_key,
            "/api/v2/bulk-update-files",
            {"data": {"fileIds": ids, "updatedObj": {"TranscodeDecisionMaker": "Queued"}}},
        )
        print(f"queued={len(ids)}")
    return 0


def selected_paths(args: argparse.Namespace) -> list[str]:
    paths = list(args.file or [])
    if args.paths_file:
        paths.extend(
            line.strip()
            for line in Path(args.paths_file).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not paths:
        raise RuntimeError("queue-paths requires --file or --paths-file")
    if any(not Path(path).is_absolute() for path in paths):
        raise RuntimeError("queue-paths requires absolute paths")
    return list(dict.fromkeys(paths))


def queue_paths(args: argparse.Namespace) -> int:
    paths = selected_paths(args)
    api_key = os.environ.get("TDARR_API_KEY")
    if not api_key:
        raise RuntimeError("TDARR_API_KEY must be set for queue mode")

    files = tdarr_files(args.tdarr_url, api_key)
    tdarr_by_path = {item.get("_id"): item for item in files}
    candidates: list[tuple[str, str, str]] = []
    missing: list[str] = []
    skipped: list[tuple[str, str]] = []
    for path in paths:
        tdarr_path = path.replace(args.media_root, args.tdarr_media_root, 1)
        db_item = tdarr_by_path.get(tdarr_path)
        if not db_item:
            missing.append(path)
            continue
        status = str(db_item.get("TranscodeDecisionMaker", ""))
        if status == "Transcode success" and not args.force:
            skipped.append((path, status))
            continue
        candidates.append((path, db_item["_id"], status))

    print(f"selected={len(paths)} queueable={len(candidates)}")
    for path, _, status in candidates:
        print(f"queue: {path} (current status: {status or 'unset'})")
    for path, status in skipped:
        print(f"skip: {path} (current status: {status}; use --force to override)")
    for path in missing:
        print(f"missing: {path} (not found in Tdarr)")

    if not args.execute:
        print("dry-run: pass --execute to queue files")
        return 0
    ids = [file_id for _, file_id, _ in candidates]
    if ids:
        api_call(
            args.tdarr_url,
            api_key,
            "/api/v2/bulk-update-files",
            {"data": {"fileIds": ids, "updatedObj": {"TranscodeDecisionMaker": "Queued"}}},
        )
    print(f"queued={len(ids)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "queue", "queue-paths"])
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--output", default="tdarr-inventory.json")
    parser.add_argument("--group")
    parser.add_argument("--tdarr-url", default="http://tdarr.local.hejsan.xyz")
    parser.add_argument("--media-root", default="/mnt/storage/files")
    parser.add_argument("--tdarr-media-root", default="/media/files")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--file", action="append", help="absolute media path; repeat for multiple files")
    parser.add_argument("--paths-file", help="file containing one absolute media path per line")
    parser.add_argument("--force", action="store_true", help="allow queueing files already marked successful")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required; install ffmpeg on the inventory host")
    roots = [Path(root).resolve() for root in (args.root or DEFAULT_ROOTS)]
    if args.command == "inventory":
        records = inventory(roots)
        Path(args.output).write_text(json.dumps(records, indent=2) + "\n")
        print(f"wrote={args.output} files={len(records)}")
        return 0
    if args.command == "queue-paths":
        return queue_paths(args)
    source = Path(args.output)
    if not source.exists():
        raise RuntimeError(f"inventory does not exist: {source}")
    return queue_group(args, json.loads(source.read_text()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
