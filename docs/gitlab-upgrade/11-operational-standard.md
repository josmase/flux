# Operating standard for GitLab Stops 3–7

This is the required procedure for every remaining GitLab upgrade stop. Each
stop document supplies only its version-specific changes and checks; this file
supplies the safety gates, manual-window discipline, Flux handoff, and recovery
rules established by Stop 2.

## 1. Hard preflight gates

Do not start a stop until each gate is recorded as passing in its change record.

| Gate | Required evidence |
| --- | --- |
| Git and Flux | `git ls-remote origin main` succeeds; `flux-system` GitRepository, `infra-controllers`, `infra-configs`, `apps-gitlab-bootstrap`, `apps-gitlab-db-bootstrap`, and `apps-gitlab` are Ready. |
| Helm | `gitlab`, `gitlab-runner`, and `traefik` HelmReleases are Ready; `helm history` has a deployable current revision. Do not begin with a failed or pending Helm action. |
| No stuck deletion | No critical GitLab, Traefik, CNPG, or storage resource has a `deletionTimestamp`. Inspect Services and their finalizers, especially LoadBalancer Services. |
| Database | `gitlab-postgres` has three Ready instances, current backup evidence, expected free capacity, and application connectivity through `gitlab-postgres-rw.gitlab.svc`. |
| Valkey | `gitlab-valkey` is Ready; unauthenticated `PING` is rejected, authenticated `PING` returns `PONG`, and the recorded persistence probe passed. |
| Storage | LINSTOR satellites are Online with the committed `worker-network` policy. Gitaly’s volume lists a `/dev/drbd…` device, its replicas are `UpToDate`, and Gitaly is Ready. |
| Artifacts | Target chart is locally available; target images are resolvable and can be pulled on the nodes that can run GitLab Jobs and Gitaly. |
| Backup | Fresh Rails and Registry dumps are non-zero; actual SHA-256 values are calculated and recorded; the files are copied off-cluster. A restore rehearsal is required for any database topology or major-version change. |
| Git ownership | The target commit, rendered manifests, and rollback commit are prepared and validated before writers are stopped. |

Useful commands:

```bash
flux get sources git -n flux-system
flux get kustomizations -n flux-system
flux get helmreleases -A
kubectl -n gitlab get cluster gitlab-postgres
kubectl -n gitlab get pods,pvc
kubectl -n piraeus-datastore exec deploy/linstor-controller -- \
  linstor volume list -r <gitaly-pv-name>
kubectl get svc -A -o json | jq -r \
  '.items[] | select(.metadata.deletionTimestamp != null) | [.metadata.namespace,.metadata.name,.metadata.deletionTimestamp] | @tsv'
```

## 2. Prepare the stop

1. Create a stop branch from current `main`; make only the version-specific
   manifest changes in the stop document.
2. Build the production target and render the Helm values. Confirm that no
   chart-managed ingress, bundled database, or bundled Redis is reintroduced.
3. Run the repository validation suite and record its output.
4. Push the branch while GitLab is healthy. Confirm that the remote contains
   the exact commit. Do not rely on an unpushed local emergency branch.
5. Record the current Helm release revisions and make a verified Git bundle or
   equivalent out-of-band copy of the known-good configuration.

## 3. Suspended manual window

1. Suspend the GitLab Kustomization and HelmRelease before altering GitLab:

   ```bash
   flux suspend kustomization apps-gitlab -n flux-system
   flux suspend helmrelease gitlab -n gitlab
   ```

2. Record that Flux source-controller remains running. Do not restart it while
   GitLab is its source.
3. Stop only the writers required by the stop. Keep Gitaly and its PVC intact
   unless the stop explicitly calls for a controlled Gitaly restart.
4. Create and verify both database dumps. Use the actual running PostgreSQL
   major version or a newer compatible client. Use strict restore flags when a
   restore is in scope:

   ```bash
   pg_restore --exit-on-error --no-owner --no-privileges --role=<application-role>
   ```

5. Run the manually rendered GitLab Helm release with an explicit timeout.
   Never pass a HelmRelease YAML directly as a Helm values file; render the
   values first. Do not use `--atomic` for a release whose database migrations
   make an automatic chart rollback unsafe.
6. Wait for migrations, then restore writers in the dependency order stated by
   the stop. Any failed migration, storage attach, or image pull is a stop
   condition, not an invitation to continue to the next version.

## 4. Acceptance gates

All of the following must pass before the GitOps handoff:

```bash
kubectl -n gitlab exec deploy/gitlab-toolbox -- \
  curl -fsS http://gitlab-webservice-default:8080/-/health
kubectl -n gitlab exec deploy/gitlab-toolbox -- gitlab-rake gitlab:gitaly:check
kubectl -n gitlab get pods
helm -n gitlab status gitlab
```

Also perform the stop-specific checks: Registry push/pull/delete where
applicable, a real Git clone/push using a disposable project, a runner job, and
the required background-migration status. `gitlab:check` output from Toolbox
must be interpreted in context: Toolbox cannot prove that Shell or Sidekiq are
running, so check those Kubernetes workloads directly.

## 5. GitOps handoff

1. Commit the acceptance-gated resume change (for example, set
   `apps-gitlab.spec.suspend: false`) and push it to `main` only after manual
   acceptance is complete.
2. Reconcile in dependency order. A successful Git fetch alone is not enough:

   ```bash
   flux reconcile source git flux-system -n flux-system
   flux reconcile kustomization infra-controllers -n flux-system --with-source
   flux reconcile kustomization infra-configs -n flux-system --with-source
   flux reconcile kustomization apps-gitlab-bootstrap -n flux-system --with-source
   flux reconcile kustomization apps-gitlab-db-bootstrap -n flux-system --with-source
   flux reconcile kustomization apps-gitlab -n flux-system --with-source
   ```

3. The stop is complete only when the source, dependency Kustomizations,
   GitLab Kustomization, GitLab HelmRelease, and runner HelmRelease are all
   Ready at the pushed revision.

## 6. Recovery rules

- Do not delete a HelmRelease merely because it is `Stalled`.
- First inspect Helm history, controller logs, live resources, events,
  `deletionTimestamp`, and finalizers. Repair the concrete resource that is
  blocking reconciliation.
- For a stale terminating LoadBalancer Service: verify the requested IP,
  MetalLB allocation, and endpoints; remove only the stale finalizer; then
  verify the replacement Service has the same external IP and endpoints.
- For a failed Flux Helm action with healthy resources, establish a valid
  deployed Helm revision before attempting remediation. Do not use direct Helm
  to take ownership of an unrelated Flux-owned release unless this recovery is
  documented and the live manifest is unchanged.
- If GitLab cannot serve the Flux repository, use the verified local bundle to
  apply the known-good GitLab manifests. Do not restart source-controller or
  rely on an `emptyDir` artifact surviving a restart.
- Roll back only to the recorded prior stop. Do not cross database-topology or
  major-version boundaries without the corresponding restore plan.

## 7. Database-bootstrap secret rotation

The database-provisioner updates an existing application role password when it
reruns a claim. It also updates the corresponding Kubernetes Secret. GitLab
workloads copy that Secret into an `emptyDir` during their init phase, so they
do not automatically observe the new password. After any claim rerun that
updates `gitlab-external-db` or `gitlab-registry-external-db`:

1. Test the current Secret against the target database role without printing
   its value.
2. Restart every workload that mounts the changed Secret (for Rails this
   includes webservice, Sidekiq, Toolbox, and exporter) before declaring the
   database healthy.
3. Verify application database connectivity plus Git HTTP before beginning a
   chart upgrade.

Record the restart and the post-reload validation in the stop change record.
