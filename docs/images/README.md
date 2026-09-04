# Re-Gear logos

Both PNGs are original user-supplied artwork, preserved without modification.

- `re-gear-icon.png`: detailed GitHub README artwork with tagline.
- `re-gear-decky-icon.png`: simplified Decky icon and panel-header artwork.
- `hdm-icon.jpg`: retained legacy Handheld Dock Mode artwork.

The Decky build embeds the simplified PNG locally through `rollup.config.js`;
it does not depend on GitHub, a network request, or a renamed plugin path.
These files do not change the plugin's installation identity or safety behavior.
# Current Decky icon

0.3.11 uses `re-gear-decky-white-transparent.png`, the exact white
gear-and-handheld RGBA PNG supplied through the user's shared ChatGPT image.
The black gear fill is absent; transparent areas reveal the Decky row color.
The prior icon assets remain preserved below.

0.3.6 uses `re-gear-decky-transparent.png`, a background-extracted derivative
of `re-gear-decky-black-gear.jpg`, made using the built-in image editing tool.
Verified RGBA with 668393 fully transparent pixels and transparent corners.
Prompt: Remove only the outside white background to genuine transparent PNG;
preserve the black gear, opaque white rings/controller and black controls;
retain a thin white silhouette edge, without added text, shadows or checkerboard.

As of 0.3.5, use `re-gear-decky-black-gear.jpg`: the latest user-supplied
black gear/handheld on white. Original bytes and white background are retained.
The 0.3.4 image below is now historical; no originals were removed.

`re-gear-decky-monochrome.jpg` is the unmodified user-supplied gear/handheld
icon selected on 2026-09-04 for the Decky list and panel header (0.3.4).
Earlier PNG originals below are retained for reference and README use.
