# RT Repair Wave 1 Checklist

Last updated: 2026-03-28

## Scope

This checklist is the first rt-only repair wave after qB shutdown.

Use it for the `19` items where:
- rt is the only live client now
- the session path is still wrong
- the good `/pool/media` target already exists on disk

These are direct repoint candidates, not donor/rebuild cases.

Reference:
- `docs/operations/RT-QB-DRIFT-HANDOFF.md`
- `out/rt-qb-savepath-drift-action-plan-2026-03-27.json`

## Required Procedure For Each Item

1. confirm the `/pool/media` target exists
2. confirm rt still points at the listed old path
3. repoint rt to the `/pool/media` target
4. verify rt resolves the correct content
5. mark the item fixed or blocked

## Success Criteria

- rt path updated to the `/pool/media` target
- no missing-content regression
- item removed from the former `fix_now_repoint_rt_to_pool_media` bucket on the next sweep

## Checklist

### 1. Subservience

- hash: `2fd37137ebdb0f6c1683aa2d222e2f48007a5116`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Subservience.2024.1080p.Remux.AVC.DTS-HD.MA.5.1-playBD/Subservience.2024.1080p.Remux.AVC.DTS-HD.MA.5.1-playBD.mkv`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Subservience.2024.1080p.Remux.AVC.DTS-HD.MA.5.1-playBD`

### 2. How It's Made S25

- hash: `323291dd08eb4d75b8a822f7f2ee5ec3497b953d`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/How.Its.Made.S25.1080p.WEB.x264-CAFFEiNE`
- old rt path: `/pool/data/cross-seed-link/FileList.io/How.Its.Made.S25.1080p.WEB.x264-CAFFEiNE`

### 3. UEFA

- hash: `3e82f6f7a3a5adae52d84a1074b290b42ccb5026`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/UEFA.Europa.Conference.League.CFR.Cluj.vs.Neman.Grodno.25.07.2024.1080i.HDTV.MPA2.0.H.264-playTV/UEFA.Europa.Conference.League.CFR.Cluj.vs.Neman.Grodno.25.07.2024.1080i.HDTV.MPA2.0.H.264-playTV/UEFA.Europa.Conference.League.CFR.Cluj.vs.Neman.Grodno.25.07.2024.1080i.HDTV.MPA2.0.H.264-playTV.mkv`
- old rt path: `/pool/data/cross-seed-link/FileList.io/UEFA.Europa.Conference.League.CFR.Cluj.vs.Neman.Grodno.25.07.2024.1080i.HDTV.MPA2.0.H.264-playTV/UEFA.Europa.Conference.League.CFR.Cluj.vs.Neman.Grodno.25.07.2024.1080i.HDTV.MPA2.0.H.264-playTV`

### 4. Command And Conquer Red Alert 3

- hash: `5b13542670579f80881b496032cb95db09e352af`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Command.And.Conquer.Red.Alert.3-RELOADED`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Command.And.Conquer.Red.Alert.3-RELOADED`

### 5. Hidden Figures

- hash: `5c877f46f4d9fa0d8ea18bf72fe6711680d03cf6`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Hidden.Figures.2016.1080p.BluRay.REMUX.AVC.DTS-HD.MA7.1.RoSubbed-playBD`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Hidden.Figures.2016.1080p.BluRay.REMUX.AVC.DTS-HD.MA7.1.RoSubbed-playBD`

### 6. Mighty Monsterwheelies

- hash: `64b13ed5f0983dec463657003039b0d136356833`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Mighty.Monsterwheelies.S01.1080p.NF.WEB-DL.DD+5.1.H.264-playWEB`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Mighty.Monsterwheelies.S01.1080p.NF.WEB-DL.DD+5.1.H.264-playWEB`

### 7. The Dark Tower

- hash: `686cc642a898e5604bc4322c734372225fbc49b9`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/The.Dark.Tower.2017.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-playBD`
- old rt path: `/pool/data/cross-seed-link/FileList.io/The.Dark.Tower.2017.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-playBD`

### 8. His Three Daughters

- hash: `691f3d9453c501ed0dff9ac7c85978389a332ab2`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/His.Three.Daughters.2024.1080p.NF.WEB-DL.DD+5.1.H.264-playWEB.mkv`
- old rt path: `/pool/data/cross-seed-link/FileList.io`

### 9. Twin Peaks S03

- hash: `6d99af9fac17e08c4f68f5caa26a78ee11531888`
- target: `/pool/media/torrents/seeding/cross-seed/YOiNKED (API)/Twin.Peaks.S03.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb`
- old rt path: `/data/media/torrents/seeding/rtorrent/Twin.Peaks.S03.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb`

### 10. Barski - Land of Lisp

- hash: `6e2271b54cf57ae7a574655af1c9c403b44dc455`
- target: `/pool/media/torrents/seeding/cross-seed-link/MyAnonamouse/Barski - Land of Lisp.pdf`
- old rt path: `/pool/data/cross-seed-link/MyAnonamouse`

### 11. Nobody Wants This

- hash: `7654bd1c57064fad6d4708cfff0ff61d80a74d1a`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Nobody.Wants.This.S01.1080p.NF.WEB-DL.DD+5.1.Atmos.H.264-playWEB`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Nobody.Wants.This.S01.1080p.NF.WEB-DL.DD+5.1.Atmos.H.264-playWEB`

### 12. Black Mirror Bandersnatch

- hash: `9e40638a670a51d611e4cc35b74ff1b936191208`
- target: `/pool/media/torrents/seeding/cross-seed-link/XSpeeds/Black.Mirror.Bandersnatch.2018.REPACK.1080p.WEB.X264-DEFLATE[xsp]`
- old rt path: `/pool/data/cross-seed-link/XSpeeds/Black.Mirror.Bandersnatch.2018.REPACK.1080p.WEB.X264-DEFLATE[xsp]`

### 13. The Roman Invasion of Britain

- hash: `b95856e0a29bf045e76a95f4ea3cacf6e4b02add`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
- old rt path: `/pool/data/cross-seed-link/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`

### 14. Burying The Ex

- hash: `ccce5140f696f61f0974f30ca7bdf516df3d9fe7`
- target: `/pool/media/torrents/seeding/cross-seed/YUSCENE (API)/Burying.The Ex.2014.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-T00thLe$$.mkv`
- old rt path: `/data/media/torrents/seeding/rtorrent`

### 15. Beetlejuice

- hash: `e04e524750c999acfc9afd5c9a604e12fbaee0d8`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/Beetlejuice.1988.1080p.Remux.VC-1.TrueHD.5.1-playBD/Beetlejuice.1988.1080p.Remux.VC-1.TrueHD.5.1-playBD/Beetlejuice.1988.1080p.Remux.VC-1.TrueHD.5.1-playBD.mkv`
- old rt path: `/pool/data/cross-seed-link/FileList.io/Beetlejuice.1988.1080p.Remux.VC-1.TrueHD.5.1-playBD/Beetlejuice.1988.1080p.Remux.VC-1.TrueHD.5.1-playBD`

### 16. How It's Made S26

- hash: `e82d4f70f2208606b4edeaf9d63bea8f6cf94481`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/How.Its.Made.S26.1080p.WEB.x264.1-CAFFEiNE`
- old rt path: `/pool/data/cross-seed-link/FileList.io/How.Its.Made.S26.1080p.WEB.x264.1-CAFFEiNE`

### 17. The Edge of Sleep

- hash: `e877206febb54ade01292c0445aee4c7a0695923`
- target: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/The.Edge.of.Sleep.S01.1080p.AMZN.WEB-DL.DDP5.1.H.264-playWEB`
- old rt path: `/pool/data/cross-seed-link/FileList.io/The.Edge.of.Sleep.S01.1080p.AMZN.WEB-DL.DDP5.1.H.264-playWEB`

### 18. Domestika - 3D Character Design and Illustration

- hash: `f8c32150f29d7e99be44273d4c7e0605a596c130`
- target: `/pool/media/torrents/seeding/cross-seed-link/DocsPedia/Domestika - 3D Character Design and Illustration`
- old rt path: `/pool/data/cross-seed-link/DocsPedia/Domestika - 3D Character Design and Illustration`

### 19. The Last Stop in Yuma County

- hash: `fad3310db364ee7a8e97d511a85cf4df1eab4813`
- target: `/pool/media/torrents/seeding/cross-seed-link/FearNoPeer/The Last Stop in Yuma County 2023 1080p AMZN WEB-DL DDP5 1 H 264-BYNDR.mkv`
- old rt path: `/pool/data/cross-seed-link/FearNoPeer`
