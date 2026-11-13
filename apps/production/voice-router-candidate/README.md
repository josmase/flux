# Wyoming voice services

This production overlay keeps Wyoming Whisper and Piper. The Ollama chat
backend and Kokoro TTS deployment were removed from Flux so the GTX 1070 is
available for LM Studio model inference.

The Ollama namespace and `voice-models` PVC remain managed to preserve their
existing data; they have no active workload. The Whisper model PVC and the
Home Assistant context secret also remain managed. Whisper runs on CPU with a
pinned, checksum-verified large-v3-turbo model. Piper runs on CPU.

Whisper receives Home Assistant's conversation-exposed entity names, aliases,
areas, and floors through its name-reading API. Its token is mounted from the
SOPS-encrypted `whisper-homeassistant-context` Secret and is never placed in
process arguments or plain environment variables. Wyoming uses the token only
to refresh transcription context; it does not call Home Assistant services.
