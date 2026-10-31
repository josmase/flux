# GitLab object storage audit

Issue #3 tracks identity separation and bucket access. The deployed GitLab
chart is 8.11.2. On 30 October 2026, all three live chart Secrets pointed
to `http://192.168.1.102:9000` in region `us-east-1` (the Toolbox
configuration does not specify a region). The production HelmRelease
configures these storage consumers:

| Consumer | Bucket | Secret and key | Required access |
| --- | --- | --- | --- |
| Rails artifacts | `gitlab-artifacts` | `gitlab-object-storage` / `connection` | List, read, write, delete and multipart |
| Rails LFS | `gitlab-lfs` | `gitlab-object-storage` / `connection` | List, read, write, delete and multipart |
| Rails uploads | `gitlab-uploads` | `gitlab-object-storage` / `connection` | List, read, write, delete and multipart |
| Rails packages | `gitlab-packages` | `gitlab-object-storage` / `connection` | List, read, write, delete and multipart |
| Rails Terraform state | `gitlab-terraform-state` | `gitlab-object-storage` / `connection` | List, read, write, delete and multipart |
| Toolbox backups | `gitlab-backups`, `gitlab-backups-tmp` | `gitlab-backup-object-storage` / `config` | List, read, write, delete and multipart |
| Registry | `linstor-backups`, prefix `gitlab-registry/` | `gitlab-registry-storage` / `config` | List prefix, read, write, delete and multipart |
| OpenTofu CI | `gitlab-terraform-state` | GitLab CI variables, outside this chart | List, read, write, delete and multipart |

The intended S3 actions for the broad bucket policies are `s3:ListBucket`,
`s3:GetBucketLocation`, `s3:ListBucketMultipartUploads`, `s3:GetObject`,
`s3:PutObject`, `s3:DeleteObject`, `s3:AbortMultipartUpload`, and
`s3:ListMultipartUploadParts`. The Registry policy restricts bucket listing
and object actions to its prefix. These are provisioned policy actions, not
proof that each consumer needs or can currently perform every action.

The five Rails buckets and the two backup buckets are created by the RustFS
Ansible role. The role provisions a GitLab workload user and an OpenTofu user
and their policies; it currently grants the Registry prefix to the workload
user. [Ansible MR !12](https://gitlab.local.hejsan.xyz/josmase/infrastructure/ansible/-/merge_requests/12)
adds separate Toolbox backup and Registry users and policies. Check the role's deployed version and live policy attachments before
changing access.

On 30 October 2026, the live Secrets named above used the same access key.
The workload identity could list all five Rails buckets and the Registry
prefix, but the Toolbox identity received `AccessDenied` for both backup
buckets. This demonstrates that the configured backup credential cannot list
those buckets; it does not establish whether backup archives exist or whether
other object operations work. The role's desired state and a Secret's name do
not prove independent identities. On 31 October 2026, the OpenTofu project CI
variables matched the dedicated RustFS identity; the identity could list its state bucket and received explicit
`AccessDenied` responses for the other six GitLab buckets. The checks did not
exercise object operations or prove the absence of inherited CI overrides. These findings are a point-in-time observation, not a health signal.

## Read-only check

Run from a trusted workstation with cluster access, Python 3, PyYAML, and
`kubectl`:

```sh
python3 utility-scripts/cluster/gitlab-storage-audit.py
```

The script reads the three live Kubernetes Secrets in memory, compares access
keys without displaying them, and signs S3 ListObjectsV2 requests for configured
buckets. It reports only HTTP status and S3 error code, never credentials or
object names. It expects the workload and backup identities to be distinct,
checks each can list its assigned buckets and receives `AccessDenied` for the
other's unrelated buckets, and checks the configured Registry prefix and
Registry access to unrelated buckets and a different prefix. The script treats
shared Registry credentials as a failure for the planned separate identity. A
missing bucket, network error, redirect, or any unexpected response fails the
check. A successful listing does not prove object reads, writes, deletion,
multipart permissions, the absence of other attached policies, or the CI
identity's access. Kubernetes Secret access is sensitive; run the script only
where this access is already authorized.

## Remaining work

1. Verify inherited CI variables and representative OpenTofu state operations;
   record results without exposing keys or state contents.
2. Apply the companion Ansible change to provision the dedicated backup
   identity and policy. Verify its allowed and denied access before deploying
   this branch's encrypted Toolbox Secret. Reconcile additively and preserve
   existing bucket contents.
3. Reconcile the encrypted Toolbox Secret from [draft MR !134](https://gitlab.local.hejsan.xyz/josmase/infrastructure/flux/-/merge_requests/134)
   only after the identity is verified; check access and coordinate the backup
   workflow with issue #5. Keep a rollback copy of the old Secret and do not
   enable backup schedules prematurely.
4. Provision and verify the Registry identity, then roll out the dedicated
   Registry Secret in [draft MR !136](https://gitlab.local.hejsan.xyz/josmase/infrastructure/flux/-/merge_requests/136). After successful pulls and pushes, remove the shared
   workload policy in a separate reviewed step. Plan the later bucket migration
   using the [Registry migration guide](../apps/production/gitlab/registry-storage-migration.md).
5. Verify representative GitLab uploads/downloads, CI state access, and backup
   operations after deployment; document evidence and any remaining exceptions.
