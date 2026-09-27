# driver_lighthouse.dll "freeze universe" patch

Target build: `lighthouse/bin/win64/driver_lighthouse.dll`
sha256 (original) `5e477db767d07d9071317e2df124acecbee151329a5400d3ecdac5d4eb849c9a`
sha256 (patched, default flags) `de7c773aed0f04115314ca6907ac73e337ff6150eeabcb33ad2da41b4b793f56`

## Why the lighthouse frame drifts

Driver-side universe (`config/lighthouse/lighthousedb.json`) is mutated at runtime:

1. **Tilt re-levelling every session.** `CLighthouseDB::UpdateBestTilt` (0x180060d10) takes the
   HMD-IMU gravity estimate for a base station, blends it into that base's dynamic state
   (`AddTiltObservation` 0x18005dfc0, log `Updating tilt for %08X`), then on bootstrap calls
   `Universe::SetTilt` (0x1800633e0) which **overwrites** the universe tilt loaded from JSON with
   the recomputed value and rebuilds `world_from_global` (u+0x54). Which base is used depends on
   which one the HMD saw first, so pitch/roll differs slightly per session.
2. **Base pose refinement.** `Universe::ApplyRelationship` (0x18005d210) moves the base that is
   farther from the origin whenever both bases already have a pose-to-global
   (log `Moving base %08X %.0fmm and %.1f deg because of relationship with ...`).
   It also pushes the new pose into tracking and re-runs SetTilt if the tilt base moved.

`SaveIfDirty` (0x180063ee0) runs from `RunFrame` every frame and writes lighthousedb.json
(log `Saved LighthouseDB rev %u`), so the drift is persisted.

## Patches (file offset / VA)

| id | site | original | patched | effect |
|----|------|----------|---------|--------|
| P2 | 0x5c72a / 0x18005d32a | `f3 0f 10 6e 20` | `e9 95 04 00 00` (`jmp 0x18005d7c4`) | skip the "both bases global" refinement branch; new bases still learn |
| P3 | 0x62883 / 0x180063483 | `f2 0f 11 46 38` | `90 x5` | SetTilt no longer stores recomputed pitch/roll into universe |
| P3 | 0x6288b / 0x18006348b | `89 46 40` | `90 x3` | SetTilt no longer stores recomputed score |
| P4 (`--no-save`) | 0x62fb0 / 0x180063bb0 | `48 89 5c 24 10` | `c3 90 90 90 90` | `CLighthouseDB::Save` becomes a no-op |
| P1 (`--no-tiltobs`) | 0x5d3c0 / 0x18005dfc0 | `48 89 5c 24 18` | `c3 90 90 90 90` | never blend HMD tilt observations into a base |

P3 keeps the "new universe" path intact: if the JSON tilt score is still the default (39.478),
SetTilt falls through to `SetOrigin` and the second, unpatched store initialises the tilt.

## Usage

```
python patch_lighthouse.py "C:\Program Files (x86)\Steam\steamapps\common\SteamVR\drivers\lighthouse\bin\win64\driver_lighthouse.dll"
python patch_lighthouse.py <dll> --no-save        # also freeze lighthousedb.json on disk
python patch_lighthouse.py <dll> --restore        # put the .orig backup back
```

The script verifies every byte before writing and aborts on a different build.
