# Delivered state set · 2026-10-03

Six accepted performances are shipped in `src/wearing/web/motion/`, selected by `character.json`. Each is 720×720, 24 fps, 120 frames, silent, approximately 0.26–0.40 MB. The main app remains http://127.0.0.1:8765/.

| State | Exact Hypit Build | Decision |
|---|---|---|
| attention v1 | bld_20261002T160809038Z_DA8756CB0C | Rejected: added a mouth. Source retained, not shipped. |
| listening | bld_20261002T160809755Z_A4CE11FD90 | Accepted after background and endpoint normalization. |
| thinking | bld_20261002T160810522Z_96FCC901DC | Accepted after background and endpoint normalization. |
| idle v1 | bld_20261002T161402405Z_B77CD83C6D | Rejected: mouth appears during breathing. Source retained, not shipped. |
| waiting | bld_20261002T161403384Z_F28358FFB6 | Accepted. |
| working | bld_20261002T161404765Z_EA192E1805 | Accepted. |
| attention corrected | bld_20261002T161405665Z_6A0FF6574F | Accepted: arm performance, fixed mouthless face. |
| idle corrected | bld_20261002T161800461Z_BE524A0CC1 | Accepted: quiet cloth/hand adjustment, fixed mouthless face. |

Eight 5-second requests at the service's quoted 9.43 credits/second = **377.20 credits estimated**, not independently reconciled account settlement. No 2K generation, new image generation, third-party subscription or top-up. User authorization covers remaining existing credits. The CLI account is usable; its token cannot read the browser-session-only balance. No claimed remaining balance or claim that every credit has been consumed. Stop at the complete useful state set rather than generating duplicates.

The `authors/*.svml` use the installed B-roll Kit and Seedance 2 Mini FrameVideo with the same independent anchor image as first and last frames. Literal 720p requests returned 960-square provider media; `finish-video.py` delivers exactly 720-square. Local finishing removes near-neutral background drift onto the existing #fafafa page, then blends eight endpoint frames toward the shared anchor. It does not paint over character defects; bad identity takes were regenerated.

Review: contact sheets sampled each source and finished performance. Browser playback confirmed currentTime advance and the actual attention clip. `output/QA.json` records 120 frames, no audio, endpoint mean absolute difference 0.59–0.61 / 255, and constant decoded corner RGB mean 249 across all frames (YUV encoding). `output/states-overview-720.mp4` is a local six-state review montage, not another generation.

Player: one persistent character container with two bounded decoder surfaces; no player controls. Ordinary state transitions finish the current gesture, handoff interrupts immediately, and a click produces one real wave then returns to the latest underlying state. V4 replaces the former rest intervals with continuous native looping. The poster is never shown at a normal loop or state boundary. Reduced motion gets the poster; hidden/offscreen video pauses. Delayed readiness cannot override a newer action. A failed source does not repeatedly retry. The exported source/run/history remain editable.


V4 correction (local processing, no extra credits): the v3 corner/endpoint QA missed a foreground exposure pulse. `finish-loop.py` now calibrates each frame against the approved head/fabric palette, retains the real performance, closes the final four frames, declares BT.709, and exports the poster from the encoded idle clip. Current outputs and numerical QA are in `output/loops-v4/`. Browser click sampling is in `.wearing/qa-loop-20261003/`.
