# Active bilingual voice deployment

This overlay is referenced by `apps/production/services` and is the active
production voice stack; never add it alongside the base references (duplicate
objects). It runs the pinned Qwen3 4B model, Whisper large-v3-turbo, and Kokoro
`af_heart` voice. The Home Assistant router uses this current model set. The
Whisper init container deletes the previous `medium-pinned` weights only after
the new model passes checksum verification. Keep the PVCs; do not preserve old
model files as a rollback path.

Whisper receives Home Assistant's conversation-exposed entity names, aliases,
areas, and floors through its name-reading API using the SOPS-encrypted
`whisper-homeassistant-context` Secret. The token is mounted as a file and is
never placed in process arguments or plain environment variables. Wyoming uses
the token only to refresh transcription context; it does not call Home Assistant
services. Online search stays disabled in the router until SOPS-encrypted
secrets are prepared for an authenticated SearXNG deployment. Do not deploy an
unauthenticated search route.

The checksummed model manifest and downloader are copies from the router repo;
CI/review must keep them identical. Normal restarts load verified PVC contents.
The Qwen GGUF chat template is imported from model metadata. Promotion requires
`/api/show` to advertise `tools` and successful real tool roundtrips; do not
assume a model name alone establishes compatibility.

Validate `linstor` provisioning on the GPU node before replacing emptyDir data.
Shared GPU capacity remains four slots; CPU preparation uses no GPU slot.
