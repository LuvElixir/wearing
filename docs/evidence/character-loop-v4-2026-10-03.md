# Wearing character loop and SVG correction — 2026-10-03

The user reported a white flash on click and requested automatic looping plus cleaner SVGs. V3 verified background corners and endpoints but missed an exposure ramp in the foreground: the idle face was about RGB 220/200/182 at the ends and 207/186/168 during playback. The controller also deliberately revealed the poster and paused between performances.

## Changes

- `design/motion/wearing-companion/states-20261003/finish-loop.py` grades each approved source frame against the independent anchor's warm head and blue fabric. Continuous per-channel curves retain the texture and shading. The background is #fafafa. The final four corrected frames settle onto the corrected first frame; the idle poster is exported from the encoded video. No generation, inpainting, or further Hypit spend.
- Six clips remain 720×720, 24 fps, 120 frames / 5 seconds, silent. BT.709 metadata is declared. Version 4 URLs invalidate old assets.
- Stable states use native video looping. Normal state changes finish the current gesture; attention is a single wave then resumes the latest state. Handoff freezes the current gesture and prepares waiting. No normal boundary exposes the poster. The last decoded image remains visible until the next decoder has a frame. Reduced motion and playback failure retain a static fallback; hidden/offscreen playback pauses.
- `mark.svg` is a clean seven-shape, four-color drawing of the cream head, two eyes, and cobalt W collar. It replaces the raster favicon/avatar. Folder, bookmark, arrows, and close glyphs have consistent rounded strokes.
- Packaging explicitly includes the web directory. A plain build initially omitted web assets under inherited ignore rules; the final wheel and sdist contain the actual assets.

## Verification

- Encoded frame inspection: all six head-material 65th-percentile RGB ranges are 1–3/255 throughout each clip. Seam head-material deltas are 0–1/255; whole-frame seam MAE is 0.582–0.616/255. These measures supplement visual inspection rather than establish pixel-perfect motion. Full metrics: `design/motion/wearing-companion/states-20261003/output/loops-v4/QA.json`.
- Real in-app browser, product player on an isolated local QA page: 66 observed loop wraps across idle, listening, thinking, and working before the final waiting test, no sampled empty media surfaces; a single visible video throughout normal playback. Waiting interrupted working, reduced motion displayed the poster, and restoring motion resumed waiting. No browser errors/warnings were reported. The test page has controls only for QA; production has no playback controls.
- Actual main app: clicked Wearing, verified `attention`, then verified automatic return to playing/looping `idle`, with poster hidden and controls false.
- 41 browser screenshot samples spanning idle → wave → idle: head-material RGB range [2,3,2], largest adjacent sampled delta [2,2,2]. Full-viewport screenshots additionally verified the character framing because clipped browser captures could offset moving video content. Measurements and screenshots: `.wearing/qa-loop-20261003/`.
- SVG inspected in browser at 24, 32, 64 and 128 pixels and in real conversation avatars.
- `node tests/test_web_motion.cjs` passed: looping, queued transitions, one-shot return, handoff, visibility, reduced motion, failure fallback, stale callbacks and no controls. JavaScript syntax checked. `uv build` passed; wheel inspected for mark.svg, six clips and v4 manifest.
- Main conversation still has four messages; before/after canonical JSON SHA-256: `467a1178ce762122b26dd8d94f406273bbe95f25bc85195bdf471b186add3982`. No conversation submissions or engine/device restarts.

The real browser verification covers the current macOS in-app browser, not every device or browser. QA server and tab are temporary; the main app stays running on port 8765.
