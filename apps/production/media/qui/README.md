# qBittorrent instance credential sync

The qBittorrent WebUI username and password are stored in the encrypted
`../qbittorrent/auth-secret.yaml`. An init container writes qBittorrent's
PBKDF2-HMAC-SHA512 WebUI hash into its persistent config before qBittorrent
starts. The Qui sync CronJob copies the same credentials into the existing
Qui instance while preserving its other settings.

The Qui management API key is stored in the SOPS-encrypted
`management-api-key-secret.yaml`. To rotate it, update `stringData.key` in that
file with:

```sh
sops apps/production/media/qui/management-api-key-secret.yaml
```

The job skips sync while the key is empty. Flux applies the encrypted Secret,
and the next five-minute run updates the Qui instance. The API key is mounted
only into this job and is never written to logs.
