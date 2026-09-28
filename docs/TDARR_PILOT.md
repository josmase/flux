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
