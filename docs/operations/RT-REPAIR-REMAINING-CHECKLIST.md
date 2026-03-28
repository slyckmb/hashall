# RT Repair Remaining Checklist

Last updated: 2026-03-28

## Scope

This checklist is the current live remainder after reevaluating the historical
`out/rt-qb-savepath-drift-action-plan-2026-03-27.json` report against the
current rt session and on-disk targets.

Generate it live with:

```bash
hashall rt repair-report \
  --report out/rt-qb-savepath-drift-action-plan-2026-03-27.json \
  --unresolved-only
```

Current remainder:

- `6` unresolved rows total
- `4` are straightforward missing-old-path repoints
- `2` are shape-specific directory/file wrapper mismatches that should be
  reviewed before repointing

## Execution Order

1. Clear the `normalize_rt_old_download_path` rows first.
2. Then manually inspect the two `investigate_shape_specific_drift` rows.

## 1. Ready Repoint: Missing Old Download Path

These are direct rt repoints. The old rt path is gone, and the preferred target
already exists on disk.

### One Day

- hash: `1309f4f204f8c13510b25ffe3697ede4d7cf234b`
- old rt path: `/downloads/complete/tv/One.Day.2024.Season.1.Complete.720p.NF.WEB-DL.x264.`
- target: `/data/media/torrents/seeding/tv/One.Day.2024.Season.1.Complete.720p.NF.WEB-DL.x264`

### 12 Monkeys (TorrentDay)

- hash: `15b92c2b2b2a528154f864a98d58961311ab9b6e`
- old rt path: `/downloads/complete/cross-seed/12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn`
- target: `/data/media/torrents/seeding/cross-seed/TorrentDay/12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn`

### 12 Monkeys (movies)

- hash: `af86f44d172a8e737d9ac8376d0465a39ed1628a`
- old rt path: `/downloads/complete/movies/12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn`
- target: `/data/media/torrents/seeding/movies/12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn/12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn.mkv`

### Long Shot

- hash: `dbe2876df3d530d9627c0b8a5469f2bfd0212008`
- old rt path: `/downloads/complete/cross-seed/Long.Shot.2019.1080p.BluRay.REMUX.AVC.Atmos-EPSiLON`
- target: `/data/media/torrents/seeding/cross-seed-link/FearNoPeer/Long.Shot.2019.1080p.BluRay.REMUX.AVC.Atmos-EPSiLON/Long.Shot.2019.1080p.BluRay.REMUX.AVC.Atmos-EPSiLON.mkv`

## 2. Manual Review: Shape-Specific Drift

These already have live content, but the rt directory and the preferred target
have different shape/depth. Review before applying a repoint.

### Top Gun 1986

- hash: `1a066555411344637d53bd97dc94057e7ddc6e63`
- current rt path: `/data/media/torrents/seeding/movies/Top.Gun.1986.4K.Remaster.1080p.BluRay.DDP.7.1.x264-HiFi`
- preferred target: `/data/media/torrents/seeding/movies/Top.Gun.1986.4K.Remaster.1080p.BluRay.DDP.7.1.x264-HiFi/Top.Gun.1986.4K.Remaster.1080p.BluRay.DDP.7.1.x264-HiFi/Top.Gun.1986.4K.Remaster.1080p.BluRay.DDP.7.1.x264-HiFi.mkv`

Review question:
- should rt point at the outer payload directory or the deeper file wrapper path?

### Vigen Guroian

- hash: `29e2b889867a8fbb4ca4748e8ba4e43e2112b98c`
- current rt path: `/data/media/torrents/seeding/myanonamouse/Vigen Guroian/Tending the Heart of Virtue How Classic Stories Awaken a Child's Moral Imagination, 2nd edition/Vigen Guroian`
- preferred target: `/data/media/torrents/seeding/myanonamouse/Vigen Guroian/Tending the Heart of Virtue How Classic Stories Awaken a Child's Moral Imagination, 2nd edition/Vigen Guroian/Tending the Heart of Virtue How Classic Stories Awaken a Child's Moral Imagination, 2nd edition/Tending the Heart of Virtue How Classic Stories Awaken a Child's Moral Imagination, 2nd edition.m4b`

Review question:
- should rt keep the author-level directory anchor, or should it be normalized to the deeper single-file wrapper path?

## Success Criteria

- all four missing-old-path rows repointed to existing targets
- the two shape-specific rows either:
  - repointed with confirmed correct path shape
  - or explicitly left as-is with rationale documented
- `hashall rt repair-report --report out/rt-qb-savepath-drift-action-plan-2026-03-27.json --unresolved-only`
  drops to zero or only intentional exceptions
