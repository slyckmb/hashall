# AGENTS — hashall repo policy

## External Repo Dependencies

| Name | Local Path | Purpose |
|------|-----------|---------|
| traktor registry | /home/michael/dev/tools/traktor/config/tracker-registry.yml | Tracker registry configuration |
| rt-tracker-manual-report | /home/michael/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py | Manual tracker report script |
| qbm config | /home/michael/dev/sys/docker/gluetun_qbit/rtorrent_vpn/config/qbm/ | qBittorrent management config |
| cross-seed config | /home/michael/dev/sys/docker/gluetun_qbit/rtorrent_vpn/config/cross-seed/ | Cross-seed configuration |
| sys/docker repo | /home/michael/dev/sys/docker/ | System Docker infrastructure |

These paths are required for mutation pre-flights. Verify each exists before running save-path-repair or rt-qb-mirror-apply.
