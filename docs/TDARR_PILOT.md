# Tdarr AV1 pilot

This pilot is intentionally separate from the Sonarr/Radarr roots. It uses a
`before/` directory containing immutable reference copies, a `work/` directory
that Tdarr is allowed to process, and an `after/` directory containing the
outputs. Production library paths are never configured as Tdarr inputs.

## Deployment

The Kubernetes manifests deploy the Tdarr Server and a CPU-only Node on the
existing `gpu=true` node. Jellyfin already claims the NVIDIA device, so the
Tdarr Node does not request `nvidia.com/gpu`.

The external 3080 worker is managed from the sibling Ansible repository. The
playbook must be run from the Ansible jumphost; it is not a local-connection
playbook. The inventory target is `192.168.1.24`:

```sh
cd /home/jonas/glab/josmase/infrastructure/ansible/ansible
ansible-playbook -i inventory/production.ini playbooks/setup-tdarr-node.yml \
  --limit tdarr-3080
```

The jumphost must have SSH access to `jonas@192.168.1.24`, privilege escalation,
the Docker Ansible collection, and the Ansible Vault password. The role mounts
`storage.local.hejsan.xyz:/files` at `/mnt/storage/files` and runs the Tdarr
Node inside Docker. The external Node uses the same Tdarr API key as the
Kubernetes Server and Node; provision that value through Ansible Vault and the
Kubernetes secret workflow, never in this repository as plaintext.

Before starting either node, create the Kubernetes Secret `media/tdarr-auth`
with key `apiKey` using the repository's normal SOPS workflow, and set the same
value as the vaulted `tdarr_api_key` for `tdarr-3080`. The Kubernetes manifests
intentionally reference this Secret but do not contain a plaintext fallback.
For example, on the jumphost, generate one `tapi_...` key, encrypt it with
SOPS in the production secret manifest, and add the same value with
`ansible-vault encrypt_string` to the Tdarr host variables. Do not paste either
value into Git or into an unencrypted command log.

## Prepare files

Run from a host with the media NFS share mounted. Paths are relative to the
directory containing the selected sample files:

```sh
utility-scripts/tdarr-pilot/prepare-sample-library.sh \
  --source-dir /mnt/storage/files/<sample-directory> \
  --output-dir /mnt/storage/files/<sample-directory>/tdarr-pilot \
  --file 1080p/sample.mkv \
  --file 1080p-hdr/sample.mkv \
  --file 4k-hdr/sample.mkv
```

Only copies are made. The original files remain in place. The generated
`work/` tree is the only tree that Tdarr may modify.

## Tdarr Flow

Configure a pilot library using the `work/` directory and use a Flow with:

1. Input File.
2. Skip files whose video codec is already AV1.
3. Set the video encoder to AV1 using `libsvtav1`. The RTX 3080 provides
   NVENC for H.264/HEVC, but does not provide AV1 encoding; its Tdarr Node is
   therefore configured with CPU workers for this AV1 pilot. Use 10-bit output
   for HDR samples.
4. Map video, audio, subtitles, and attachments.
5. Use `-c:a copy` and `-c:s copy` so audio and subtitles are not re-encoded.
6. Use MKV output.
7. Write the completed file to the matching path under the sibling `after/`
   directory.
8. Do not use Replace Original File or delete the working input.
9. Run a health check and compare the `before/` and `after/` media details.

The temporary Jellyfin pilot library should point at `after/`, never at
`before/`, `work/`, or the production movie and series roots. Audio, subtitles,
attachments, and metadata should be stream-copied; only the video stream is
transcoded.

## Manually queue selected files

For a small validation batch, use the existing controller's `queue-paths`
command. This is separate from inventory grouping: it queues only the exact
files supplied by the operator. Do not commit a live path list to Git; keep
temporary selections under `/tmp` or another operator-controlled directory.

Run the command from a host with the media NFS share mounted and access to the
Tdarr API. The host path is `/mnt/storage/files`; Tdarr sees the same files as
`/media/files` inside its containers.

The command is read-only by default. Review the candidates first:

```sh
python3 utility-scripts/tdarr-pilot/tdarr-group-rollout.py queue-paths \
  --file "/mnt/storage/files/movies/example/movie.mkv"
```

Multiple files can be supplied by repeating `--file`, or with a temporary
paths file containing one absolute path per line. Blank lines and lines
starting with `#` are ignored:

```sh
python3 utility-scripts/tdarr-pilot/tdarr-group-rollout.py queue-paths \
  --paths-file /tmp/tdarr-selected-files.txt
```

After confirming that every path is present in Tdarr and has the expected
status, queue the batch explicitly:

```sh
TDARR_API_KEY="$TDARR_API_KEY" \
python3 utility-scripts/tdarr-pilot/tdarr-group-rollout.py queue-paths \
  --paths-file /tmp/tdarr-selected-files.txt \
  --execute
```

The command reports files that are missing from Tdarr and skips files already
marked `Transcode success`. Use `--force` only when deliberately retrying a
successful file. The queued files use the configured production flow
`tdarr-av1-in-place`; no library-wide requeue is performed.

After queueing, confirm the selected paths in the Tdarr queue and verify the
worker logs before selecting another batch. The in-place flow replaces an
original only when the validated output is smaller; audio, subtitles, and
attachments remain stream-copied.

## Grouped production rollout

The production rollout is intentionally grouped by expected storage saved per
CPU-hour. The current inventory is approximately 79 TiB of movies and 16–17
TiB of series. Existing AV1, HDR, and Dolby Vision files are deferred.

The grouped controller is read-only unless `--execute` is supplied:

The inventory host must have `ffprobe` from the FFmpeg package and read access
to the NFS mount. The queue command needs `TDARR_API_KEY`, but inventory does
not need Tdarr credentials.

```sh
python3 utility-scripts/tdarr-pilot/tdarr-group-rollout.py inventory \
  --output /tmp/tdarr-inventory.json

python3 utility-scripts/tdarr-pilot/tdarr-group-rollout.py queue \
  --output /tmp/tdarr-inventory.json \
  --group legacy-1080p \
  --batch-size 6
```

Set `TDARR_API_KEY` only in the shell environment used for the queue command.
Add `--execute` only after reviewing the dry-run candidates. Run one group at a
time; repeat the bounded queue command after the previous batch drains.

The intended order is:

1. `legacy-1080p` — H.264, VC-1, and VP9 SDR.
2. `legacy-720p` and `legacy-sd` — fast, lower absolute savings.
3. `legacy-2160p` — large savings, but high CPU cost.
4. `hevc-1080p` and `hevc-2160p` — only where the pilot confirms a reduction.

`deferred-hdr`, `skip-av1`, and `deferred-unsupported` are never queued by the
controller. The inventory priority is an estimate of expected bytes saved per
runtime and must be recalibrated from completed group results.

For production in-place replacement, import
`utility-scripts/tdarr-pilot/flows/av1-in-place.json` as the flow template.
The flow replaces the original only on the smaller-output branch and restores
the original working-file reference for equal or larger outputs. Both current
nodes are mapped to the shared NFS path, which is required for Tdarr file
operations such as Replace Original File. Validate the flow against a small
production-like batch before enabling it for a complete group.
