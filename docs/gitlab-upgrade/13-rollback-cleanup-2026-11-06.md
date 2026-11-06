# GitLab rollback cleanup (2026-11-06)

GitLab `19.5.3-ee` / chart `10.5.4` was accepted by the operator. All Rails
background migrations were `finished` or `finalized`, and the GitLab
HelmRelease plus application workloads were Ready before this cleanup.

The operator explicitly waived the seven-day hold and approved permanent
removal of accessible rollback artifacts. External backup-host copies remain
out of scope.

The cleanup removes the obsolete bundled PostgreSQL, Redis, and MinIO data
paths, their LINSTOR migration snapshots, historical Helm migration Jobs and
release-history Secrets, and local upgrade dumps. Gitaly's active
`repo-data-gitlab-gitaly-0`, CNPG, Valkey, current Helm revision, active
credentials, and all production backup targets remain protected.

PVCs and snapshots are protected from Flux pruning, so Git ownership is
removed first and their Kubernetes/PV/LINSTOR resources are deleted only after
the GitOps change has converged and consumer checks have passed.
