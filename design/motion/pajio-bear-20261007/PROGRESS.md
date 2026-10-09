# Pajio bear motion — 2026-10-07

Two bounded Seedance 2 Mini samples completed through Hypit. No voice route used.

- Idle: `bld_20261007T122033516Z_814EBF632A` — blink, head turn, paw greeting; source 960 × 960, 24 fps, 5.04 seconds. Requested provider preset was 720p; received square 960px output. Reviewed a 12-frame contact sheet and playback.
- Change: `bld_20261007T122837018Z_2B6799088F` — blue stripes to cream moon; adjust collar, turn, inspect new sleeve. Reviewed contact sheet and playback. Reverse derivative supports cream to blue. App derivatives are 480px H.264, about 2.8 seconds per change.
- Published rate observed before submitting: 9.43 credits/second, estimated 47.15 each / 94.30 combined. This is an estimate, not an account balance or settled invoice. No extra paid retries or purchases.

## Integration scope

- Only blue outfit has articulated idle footage. Other seven outfits keep their matching static illustration.
- Only blue/cream pair has articulated garment transition. Other combinations use predecoded, registered images behind a short dressing curtain.
- All eight original assets are unchanged; alpha bounds register head-to-foot height, baseline and horizontal center through layout.
- Respect reduced motion and foreground visibility; no audio or playback controls in product. Idle plays once, then repeats every 23 seconds with a quiet pause.
- Wardrobe preview does not save the outfit; explicit apply retains the existing identity-scoped persistence behavior.
- Release simulator verification initially found a video disposal race on leaving chat. Cleanup now lets useVideoPlayer own native disposal; page/foreground transitions handle pause while the player is alive. Final Release build retested successfully through chat, settings, wardrobe, a completed blue/cream change and an interrupted change to peach.

Sources, author files, run definitions and unmodified generated media are retained in this directory. Native derivatives are in `clients/mobile/assets/bear-motion`. Web/Desktop is delegated to ZCode and must use those source assets without changing App code.
