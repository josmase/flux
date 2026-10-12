# Gated bilingual voice candidate

This overlay replaces the Ollama, Wyoming Whisper, and Kokoro base references in
`apps/production/services`; never add it alongside them (duplicate objects).
The existing Home Assistant pipelines remain selected while the model PVCs and
router candidate are validated. Rollback restores the three base references;
retain PVCs and old model data for seven days after hardware acceptance.

Online search stays disabled in the router until SOPS-encrypted secrets are
prepared for an authenticated SearXNG deployment. Do not deploy an unauthenticated
search route.

The checksummed model manifest and downloader are copies from the router repo;
CI/review must keep them identical. Normal restarts load verified PVC contents.
The Qwen GGUF chat template is imported from model metadata. Promotion requires
`/api/show` to advertise `tools` and successful real tool roundtrips; do not
assume a model name alone establishes compatibility.

Validate `linstor` provisioning on the GPU node before replacing emptyDir data.
Shared GPU capacity remains four slots; CPU preparation uses no GPU slot.
