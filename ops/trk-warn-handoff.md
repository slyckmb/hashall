# Handoff: prowlarr search & SNL S51 episode alternatives

## Context

`trk-warn` reported 1 deleted + 5 auth_err torrents for Saturday Night Live S51 episodes.

### Results

| Episode | Problem | Alternatives found |
|---|---|---|
| S51E18 | Deleted on aither.cc | **None** — dead everywhere |
| S51E02 | Auth err on onlyencodes.cc | hawke-uno, Bitmagnet, TorrentsCSV, MagnetDownload |
| S51E03 | Auth err on onlyencodes.cc | hawke-uno, Bitmagnet, TorrentDownload, TorrentsCSV, MagnetDownload |
| S51E04 | Auth err on onlyencodes.cc | **None** |
| S51E06 | Auth err on onlyencodes.cc | **None** |
| S51E11 | Auth err on nebulance.io | hawke-uno |

### Tool: `tools/ps.py`

Searches all 56 enabled Torznab-capable indexers via prowlarr API in parallel.

```
ps.py "Saturday Night Live S51E02"
```

Requires:
- Docker (talks to `prowlarr` container)
- Prowlarr API key embedded (currently `722e1228a4314380b07b2a813d8dc0c3`)

### Prowlarr changes made

| Change | Detail |
|---|---|
| Updated to v2.4.0.5397 | `docker compose pull && up -d` |
| Deleted SceneTime (old) | id=55 — cookie-based, obsolete definition |
| Added SceneTime (API) | id=135 — Torznab-compatible, API key configured |
| Fixed ABtorrents, DocsPedia | downloadClientId set to 0 (was pointing at disabled qBittorrent) |

### Vault changes

| File | Update |
|---|---|
| `/mnt/config/secrets/trackers/scenetime.env` | Added `SCENETIME_API_KEY` |

### Open items

- **onlyencodes.cc & nebulance.io auth_err** — 4 episodes unsearchable. Prowlarr's cookie/credential for these trackers is expired or misconfigured. Check Prowlarr → Indexers → onlyencodes/RSS → update cookie.
- **S51E18 is dead** — no copies exist on any of the 56 indexers. Needs a scene re-release or different source (WEB-DL from a different group).
