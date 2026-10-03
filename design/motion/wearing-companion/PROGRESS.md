# Production record

- Image build `bld_20261002T075347607Z_5C0CDEEC09`: independent standing character. Retained as a nonselected pose.
- User refined direction: the sleeve-rolling gesture must express ready to help and act, not passive companionship. Main copy updated to “这件事，我来。”
- Image build `bld_20261002T075939367Z_E05A298918`: independent cuff-adjusting full character. Used for the webpage poster. Image request selected 1K; provider returned 2048×2048. The web poster is locally resized to 720×720; no separate high-resolution tier was deliberately selected.
- Video build `bld_20261002T080505490Z_60FA7FB829`: 720p request, provider returned 960×960 for square aspect ratio, 6.041667 seconds, no audio. Rejected after frame review: introduced a mouth that contradicts the approved two-eye character. Keep source for QA evidence only.
- Video correction `bld_20261002T081039351Z_007AAF9AA1`: reuse the cuff image, fix head/face entirely, animate only the cuff and hand; 720p request. Complete. Frame grid preserves mouthless two-eye identity.

Budget authority: user permits using available Hypit credits for this work, with the explicit instruction to avoid waste and use 720p. Quoted plan: two images at 6.9 credits each, two six-second mini videos at 9.43 credits/second = approximately 126.96 credits; this is a quote-based estimate, not an account settlement reconciliation.

- Portrait-matting attempt `bld_20261002T081527282Z_E97848FE6B` did not retain the nonhuman character and was rejected. Final background uses local neutral-color keying via neutral-background.filter, with no further paid generation.
- Final delivery: src/wearing/web/character-cuff.mp4, 720×720, 6.041667 seconds, no audio, 265819 bytes. Poster extracted from the final first frame, manifest wired. Full decode and 12-frame review pass. Browser confirms playback, mute, loop, and pause.

- Loop v2: user observed a white flash. Frame analysis found source-character brightness pumping at both ends, not background color drift. Removed unstable ends and added a 12-frame cosine crossfade, 120 frames / 5 seconds. Updated web video, poster and manifest cache keys. Maximum adjacent-frame MAE fell from 2.454 to 0.783; first/last head ROI mean 193.704/193.851. Three browser loop boundaries retained readyState 4, visible video. No new Hypit generation or credit charge.
