# Gated bilingual voice candidate

This overlay is deliberately outside `apps-services`. Build/validate it before
promotion; do not simply add it alongside the existing voice bases (duplicate
objects). Deployment replaces the base voice references with this overlay once
prepared secrets and the rollout gates are satisfied. Rollback restores those
base references; retain PVCs and old model data for seven days after acceptance.

Prepare SOPS-encrypted Secrets in namespace `searxng`: `searxng-private` with
`secret-key`, and `searxng-auth` with htpasswd `users`. Store the corresponding
`assist` password in Ansible Vault. Never deploy an unauthenticated search route.

The checksummed model manifest and downloader are copies from the router repo;
CI/review must keep them identical. Normal restarts load verified PVC contents.
The Qwen GGUF chat template is imported from model metadata. Promotion requires
`/api/show` to advertise `tools` and successful real tool roundtrips; do not
assume a model name alone establishes compatibility.

Validate `linstor` provisioning on the GPU node before replacing emptyDir data.
Shared GPU capacity remains four slots; CPU preparation uses no GPU slot.
