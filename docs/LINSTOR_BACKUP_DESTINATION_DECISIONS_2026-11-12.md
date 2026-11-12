# LINSTOR backup destination decisions — 2026-11-12

## Destination and accepted failure risk

At the user's direction, LINSTOR recovery continues to use only the existing RustFS service at `storage.local.hejsan.xyz`, on `/srv/mergerfs/storage`, bucket `linstor-backups-v2`. This host also serves the NFS exports, which are excluded from backup by the separate approved classification decision.

The user explicitly accepted the risk of using RustFS as the only backup destination. Loss of the RustFS host, its underlying storage, or the site can destroy both the source and backup copy. The epic's requirement for a second failure-independent destination is waived by that decision. No independent copy or site-loss protection is claimed.

## Existing scoped credential and recovery material

The existing v2 credential is configured for LINSTOR's `linstor-backups-v2` bucket. The RustFS policy template grants bucket location/list/multipart-list actions on that bucket and get/put/delete/multipart actions on objects in that bucket. It does not grant access to other buckets. The policy is managed by the storage-server Ansible role.

The Kubernetes credential is stored in `infrastructure/production/configs/piraeus/rustfs-v2-credentials.yaml` as a SOPS-encrypted Secret. RustFS identity and administrator keys are referenced from the encrypted storage-server Ansible vault at `../ansible/ansible/inventory/group_vars/storage_servers/vault.yml`; plaintext credentials are not committed. Authorized Flux operators with the configured age key can recover the SOPS Secret. Authorized storage operators with the Ansible Vault recovery mechanism can recover or re-provision RustFS credentials and policy. Do not copy decrypted values into reports or shell history.

The encrypted secret and the Ansible vault are both in the same repository/admin recovery plane; this is credential recovery, not a separate backup destination. Current production operation does not prove every listed S3 action or successful restore; those remain subject to T2.4 and T3 restore gates.

## Implementation references

- Flux Secret and CSI use: `infrastructure/production/configs/piraeus/rustfs-v2-credentials.yaml`, `infrastructure/production/configs/piraeus/cnpg-s3-snapshot-class.yaml`.
- RustFS host, bucket, quota, and credential variables: `../ansible/ansible/inventory/group_vars/storage_servers/main.yml`.
- Scoped policy template: `../ansible/ansible/roles/services/rustfs/templates/linstor-backups-v2-policy.json.j2`.
- RustFS single failure-domain statement: `infrastructure/production/configs/piraeus/README.md`.
