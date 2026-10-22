# driver_lighthouse.dll "freeze universe" patch

`patch_lighthouse.py` detects the build (sha256, then byte patterns at every patch site) and
refuses unknown builds. Supported builds:

| build | sha256 (original) | sha256 (patched, default flags) |
|-------|-------------------|---------------------------------|
| 2026-10-17 | `21d29dfada45fe76f7e2bfee61a4a3fa788cc95820ef2a0fea55d7a0721be52d` | `864699a0bdd873cca5602a466729e8ad636643a51584c8c90a5f851765895db2` |
| 2026-09-16 | `eb6545c837f9d8bc780499a08e201636a1155bad58ea5206daa02830e85b1e36` | `ab715c8ca489a1af194a17f88868827ddcbc751fadd0b56711d0318068de1425` |
| 2026-09-13 | `5e477db767d07d9071317e2df124acecbee151329a5400d3ecdac5d4eb849c9a` | `de7c773aed0f04115314ca6907ac73e337ff6150eeabcb33ad2da41b4b793f56` |

## Why the lighthouse frame drifts

Driver-side universe (`config/lighthouse/lighthousedb.json`) is mutated at runtime
(VAs below are for the 2026-09-16 and 2026-10-17 builds; add 0x140 for 2026-09-13):

1. **Tilt re-levelling every session.** `CLighthouseDB::UpdateBestTilt` takes the HMD-IMU
   gravity estimate for a base station, blends it into that base's dynamic state
   (`AddTiltObservation` 0x18005de80, log `Updating tilt for %08X`), then on bootstrap calls
   `Universe::SetTilt` (0x1800632a0) which **overwrites** the universe tilt loaded from JSON with
   the recomputed value and rebuilds `world_from_global` (u+0x54). Which base is used depends on
   which one the HMD saw first, so pitch/roll differs slightly per session.
2. **Base pose refinement.** `Universe::ApplyRelationship` (0x18005d0d0) moves the base that is
   farther from the origin whenever both bases already have a pose-to-global
   (log `Moving base %08X %.0fmm and %.1f deg because of relationship with ...`).
   It also pushes the new pose into tracking and re-runs SetTilt if the tilt base moved.

`SaveIfDirty` runs from `RunFrame` every frame and writes lighthousedb.json
(log `Saved LighthouseDB rev %u`), so the drift is persisted.

## Patch sites

Bytes are identical in both builds; only offsets differ.

| id | effect | original | patched | 2026-09-16 / 2026-10-17 offset / VA | 2026-09-13 offset / VA |
|----|--------|----------|---------|------------------------|------------------------|
| P2 | skip the "both bases global" refinement branch; new bases still learn | `f3 0f 10 6e 20` | `e9 95 04 00 00` (`jmp` to epilogue) | 0x5c5ea / 0x18005d1ea → 0x18005d684 | 0x5c72a / 0x18005d32a → 0x18005d7c4 |
| P3a | SetTilt no longer stores recomputed pitch/roll into universe | `f2 0f 11 46 38` | `90 x5` | 0x62743 / 0x180063343 | 0x62883 / 0x180063483 |
| P3b | SetTilt no longer stores recomputed score | `89 46 40` | `90 x3` | 0x6274b / 0x18006334b | 0x6288b / 0x18006348b |
| P4 (`--no-save`) | `CLighthouseDB::Save` becomes a no-op | `48 89 5c 24 10` | `c3 90 90 90 90` | 0x62e70 / 0x180063a70 | 0x62fb0 / 0x180063bb0 |
| P1 (`--no-tiltobs`) | never blend HMD tilt observations into a base | `48 89 5c 24 18` | `c3 90 90 90 90` | 0x5d280 / 0x18005de80 | 0x5d3c0 / 0x18005dfc0 |

P3 keeps the "new universe" path intact: if the JSON tilt score is still the default (39.478),
SetTilt falls through to `SetOrigin` and the second, unpatched store initialises the tilt.

## Usage

```
python patch_lighthouse.py "C:\Program Files (x86)\Steam\steamapps\common\SteamVR\drivers\lighthouse\bin\win64\driver_lighthouse.dll"
python patch_lighthouse.py <dll> --no-save        # also freeze lighthousedb.json on disk
python patch_lighthouse.py <dll> --restore        # put the .orig backup back
```

Re-running is idempotent. Steam's integrity check and SteamVR updates restore the stock DLL,
so keep this script around and re-run it after every update.

