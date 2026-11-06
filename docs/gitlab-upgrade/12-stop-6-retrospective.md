# Stop 6 retrospective: GitLab 19.2.10 / chart 10.2.10

**Completed:** 2026-11-06  
**GitOps revision:** `72bb4013`  
**Helm release:** `gitlab.v39`, chart `10.2.10`  
**Runner:** chart `0.94.1`, Runner `19.5.1`

## Outcome

GitLab upgraded from `18.11.14` / chart `9.11.16` to `19.2.10` / chart
`10.2.10`. The Registry moved to `s3_v2` while retaining its RustFS bucket,
prefix, endpoint, and identity. No data-bearing PVC was deleted; Gitaly's
retained `repo-data-gitlab-gitaly-0` claim remained bound to
`pvc-d6aacc5d-85ca-412b-a52c-8245a35cf532` throughout recovery.

Verified after the final GitOps handoff:

- Flux root and `apps-gitlab` were Ready at the published target revision.
- Helm release `gitlab.v39` was Ready on chart `10.2.10`.
- Routed and in-cluster `/-/health` returned `GitLab OK`.
- `gitlab:gitaly:check` passed; CNPG was `3/3`; authenticated Valkey returned
  `PONG`.
- Webservice `2/2`, Registry `1/1`, Sidekiq `2/2`, KAS `2/2`, Shell `2/2`,
  Toolbox `1/1`, and Gitaly `1/1` were Ready.
- The Runner manager was Ready on `19.5.1` and accepted a queued CI job.
- The updated storage audit passed all scoped allow-and-deny checks with three
  distinct access identities.

Fresh pre-window and writer-quiesced Rails/Registry dumps were TOC verified;
the pre-upgrade Git bundle was also verified.

## What went wrong and how it was recovered

1. Suspending `apps-gitlab` alone was insufficient: its parent
   `flux-system` Kustomization reapplied the stale child definition and the
   old `9.11.16` HelmRelease spec. After Rails migrations, that initiated an
   unsafe rollback attempt. Writers were still at zero.
2. Applying a raw HelmRelease bypassed Flux post-build substitution, leaving
   `${DOMAIN_INTERNAL}` and `${STORAGE_CLASS}` literal. The migration hook
   failed before running migrations because of the literal GitLab host.
3. The first Gitaly StatefulSet recreation used the unresolved storage class.
   Kubernetes correctly rejected the later immutable `volumeClaimTemplates`
   change.
4. Deleting a Helm hook Job while Helm was waiting for it caused a separate
   Helm timeout. Do not use hook deletion to unblock an active action.

Recovery was forward-only: suspend the parent and child Kustomizations plus
the HelmRelease, restore the target spec with resolved values, recreate only
the Gitaly StatefulSet after confirming `Retain/Retain` PVC policy, and retry
through the Flux Helm controller. Upgrade remediation is now pinned to
`retries: 0` and `remediateLastFailure: false`.

## Learnings for Stop 7

- Publish the target commit and verify Flux can fetch it before stopping
  writers. GitLab is the Flux source and cannot receive a corrective commit
  while webservice is unavailable.
- When temporary live state differs from Git, suspend the complete Flux
  ownership path, not just the leaf. Get approval before pausing a broad parent
  because it halts unrelated reconciliation.
- Do not apply an unsubstituted source manifest directly. Use Flux-rendered
  output or resolve every post-build substitution first.
- For an immutable StatefulSet mismatch, first record the PVC and verify
  `whenDeleted` and `whenScaled` are `Retain`; recreate only the StatefulSet,
  never the PVC.
- Cold pulls of the 1.2 GB Toolbox and webservice images took several minutes;
  treat image availability as a maintenance-window dependency.
- The storage audit supports legacy `s3` and `s3_v2`. Its result verifies
  listing and authorization scope, not Registry write/delete behavior.

## Remaining acceptance item

Registry readiness, metadata database startup, online GC, and scoped
object-store access were validated. A disposable Registry push/pull/tag-delete
test was not run. Complete and record that test before accepting Stop 7; do
not infer it from the storage audit.
