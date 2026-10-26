# NFS workload recovery rollout — 2026-10-26

## Delivered implementation

Rust source project: `josmase/infrastructure/nfs-stale-mount-recovery`, branch
`codex/workload-nfs-recovery`. Implementation commit 191fedcf8df46c31646f4171501a87ece5404c47.
The sidecar is separate from the existing privileged node agent.

Hosted production image:
`artifactory.local.hejsan.xyz/local/nfs-workload-recovery@sha256:0aae98b27425b4fbdf0f73d37ad2d47f55f64394c1d90b7b053558409d6f193c`.
Image revision label identifies the implementation commit. The image runs
non-root, has no shell or kubectl dependency, and uses the Kubernetes API.

The generic Kustomize component is under
`apps/base/components/nfs-stale-recovery`; Immich is the first adopter.
Jellyfin migration manifests are staged as examples but remain inactive
until Immich passes its overnight observation. Existing Jellyfin probes,
initialization, storage and application image remain unchanged.

## Validation

- Rust: 18 test functions passed, including property-based cases; formatting
  and Clippy with warnings denied passed.
- LLVM line coverage: 96.07% over all production Rust code, with no production
  files excluded. Budget, configuration and detection modules each 100%.
  This is line coverage, not a claim of complete branch coverage.
- Mock API cases cover ownership, UID preconditions, maintenance pauses,
  optimistic concurrency, malformed state, retries, token rotation,
  authentication/transport failures, and oversized/truncated responses.
- Disposable kind cluster (Kubernetes 1.34): persistent synthetic stale faults
  caused exactly three reserved graceful replacements; the next pod stayed
  alive after budget exhaustion. SSA preserved runtime state. Pausing the
  Deployment suppressed deletion even after resetting the test budget.
- Isolated NFS server/client: the Rust path checker returned 116 for a real
  stale handle. The scripted NFS-backed workload test then recovered from
  a stale application subPath through one graceful pod replacement; the
  new pod read the fresh recovery marker. Only disposable data was changed.
- Kustomize validation covers Immich and staged Jellyfin migration,
  distinct state/RBAC in one namespace, immutable image reference,
  read-only parent mounts, and unchanged Jellyfin application behavior.
- Production image-pull smoke test succeeded on node 206 with the GitLab
  registry restored to its original zero replicas.

## Publishing and operational notes

The GitLab registry and CI runner were initially scaled to zero. The registry
was temporarily started solely to publish the image and restored afterward.
Temporary credential-helper configuration used existing GitLab keyring
credentials, was isolated from the user's Docker configuration, and cleaned
up. No credentials were copied into workload manifests or service accounts.

The GitLab pull-through route returned 404 for the new image. The tested
image was instead published to the existing hosted Artifactory `local`
Docker repository, so runtime pulls do not depend on GitLab being running.
CI publishes sidecar images to this hosted repository independently of the
node-agent pipeline. CI jobs remain queued while the runner is at zero;
local checks and acceptance results above are verified, not a CI-success claim.

No mergerfs settings, node recovery-agent configuration, PV/PVC contents,
or K3s versions were changed by this rollout.

## Acceptance before Jellyfin promotion

Verify Immich remains Ready, both actual application mount paths are
readable, API ping returns pong, and its next overnight database backup
completes with a stable final archive. Inspect retry history/events for any
recovery loops or exhausted budget. Then activate the prepared Jellyfin
migration, rerender and validate, verify HTTP health and playback, and retain
state ConfigMaps for diagnosis. Do not start a K3s upgrade as part of this task.
