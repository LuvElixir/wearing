# Wearing · 折带 W

Approved direction: the user chose A from `../20261004/symbol-concepts.png` on 2026-10-05. Brand identifier and companion are separate: the folded W identifies the application; the established 3D blue sleeve character remains in greetings, conversations and feedback.

The W is a broad, continuous fabric-like silhouette with two pale reverse faces and one raised cuff. The vector master uses five filled paths, two solid colors, no fonts, strokes, filters or embedded raster. Its flowing edges are optical curves, not a snapped engineering grid. The SVG audit's near-angle warnings are deliberate fabric geometry, not a requirement to regularize them.

- Master: `wearing-symbol.svg`; black and white masters are included.
- iOS / standard application icon: `wearing-app.svg`, opaque white full-bleed source; let the OS apply its mask.
- macOS / Windows: `wearing-desktop.svg`, white rounded tile with transparent exterior; `desktop/` contains ICNS, ICO and PNG sizes.
- Android: transparent `wearing-adaptive.svg`, icon footprint kept inside the central 66% safe region; `wearing-adaptive-mono.svg` for themed icons. App config uses a white background.
- Browser: `favicon.ico` and the full SVG symbol.

Colors: front #4562DC; reverse fold #97A9F7; background #FFFFFF; monochrome ink #1C2331. Keep at least one ribbon width around a standalone symbol. Minimum rendered symbol 16px; use two-color or single-color variants without adding extra details. Retain original wordmark geometry.

Rebuild vector wrappers with `python3 design/icons/folded-w/build.py`; rasterize with the installed logo-design renderer and package platform icons with Tauri CLI. `preview.png` shows the actual SVG at large, 64, 32 and 16px, plus monochrome/reversed variants. It is a design implementation, not trademark clearance.
