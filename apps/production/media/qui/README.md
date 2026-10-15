# qBittorrent instance credential sync

The qBittorrent WebUI username and password are stored in the encrypted
`../qbittorrent/auth-secret.yaml`. Each instance has its own persistent config;
the init container writes qBittorrent's PBKDF2-HMAC-SHA512 WebUI hash before
the service starts. The Qui sync CronJob copies the shared credentials into
five pre-created Qui instances while preserving their other settings.

The job creates Qui entries named `qBittorrent` and `qBittorrent-2` through
`qBittorrent-5` when they are missing, then keeps their service URLs and shared
credentials aligned every five minutes.

Arr routing still uses the existing Qui client proxy key until five
instance-specific proxy URLs are available. Qui creates these under
Settings → Client Proxy, and each key is bound to exactly one instance. Once
created, store their encrypted values in Configarr before applying the balanced
Sonarr/Radarr assignment. Keep each generated URL with its corresponding
instance; one proxy key cannot route to multiple qBittorrent instances.

The balanced assignment follows the existing Configarr order (Sonarr 1–6,
then Radarr 1–12):

| Instance | Arr clients |
| --- | --- |
| `qBittorrent` | Sonarr 1, Sonarr 6, Radarr 5, Radarr 10 |
| `qBittorrent-2` | Sonarr 2, Radarr 1, Radarr 6, Radarr 11 |
| `qBittorrent-3` | Sonarr 3, Radarr 2, Radarr 7, Radarr 12 |
| `qBittorrent-4` | Sonarr 4, Radarr 3, Radarr 8 |
| `qBittorrent-5` | Sonarr 5, Radarr 4, Radarr 9 |

The Qui management API key is stored in the SOPS-encrypted
`management-api-key-secret.yaml`. To rotate it, update `stringData.key` in that
file with:

```sh
sops apps/production/media/qui/management-api-key-secret.yaml
```

The job skips sync while the key is empty. Flux applies the encrypted Secret,
and the next five-minute run updates the Qui instances. The API key is mounted
only into this job and is never written to logs.
