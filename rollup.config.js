import deckyPlugin from "@decky/rollup";
import { readFileSync } from "node:fs";
import { composeCommandCenterArtwork } from "./scripts/compose_command_center_artwork.mjs";
import { buildProfilePlugin } from "./scripts/build_profile_contract.mjs";

const config = deckyPlugin({});
config.plugins.push(buildProfilePlugin());
// Bundle the repository attribution sources; no runtime file or network reads.
config.plugins.unshift({
  name: "re-gear-project-documents",
  resolveId(source) { return source === "regear:project-documents" ? "\0regear:project-documents" : null; },
  load(id) {
    if (id !== "\0regear:project-documents") return null;
    const notices = readFileSync(new URL("./THIRD_PARTY_NOTICES.md", import.meta.url), "utf8");
    const license = readFileSync(new URL("./LICENSE", import.meta.url), "utf8");
    return `export const noticesText=${JSON.stringify(notices)};export const licenseText=${JSON.stringify(license)};`;
  },
});

// Bundle the owner-approved, self-contained V3 production family. The numbered
// filenames are explicit so an arbitrary repository path can never become a
// build-time or runtime asset read through this virtual module.
const v3ProductionTiles = new Set([
  "01_fps", "02_battery", "03_controller", "04_egpu", "05_display",
  "06_performance", "07_manual-tdp", "08_auto-tdp", "09_handheld",
  "10_safe-disconnect", "11_disconnect-sleep", "12_disconnect-shutdown",
  "13_resolution", "14_refresh-rate", "15_storage", "16_wifi", "17_mic",
  "18_record", "19_brightness", "20_volume", "21_offline-ready", "22_charging",
  "23_temperature", "24_fan", "25_network", "26_game-ready", "27_player-order",
  "28_audio-output", "29_gpu-load", "30_power-draw", "31_frametime", "32_memory",
  "33_clock", "34_quick-access", "35_settings", "36_about", "37_more",
]);
config.plugins.unshift({
  name: "re-gear-command-center-v3-production",
  resolveId(source) {
    const normalized = source.replaceAll("\\", "/");
    const match = /assets\/command-center\/v3\/production\/(\d{2}_[a-z-]+)\.svg\?v3-production$/.exec(normalized);
    return match && v3ProductionTiles.has(match[1]) ? `\0re-gear-command-center-v3-production:${match[1]}` : null;
  },
  load(id) {
    const prefix = "\0re-gear-command-center-v3-production:";
    if (!id.startsWith(prefix)) return null;
    const name = id.slice(prefix.length);
    if (!v3ProductionTiles.has(name)) return null;
    const tile = readFileSync(new URL(`./assets/command-center/v3/production/${name}.svg`, import.meta.url));
    return `export default ${JSON.stringify("data:image/svg+xml;base64," + tile.toString("base64"))};`;
  },
});

const richTileSpriteImport = "assets/command-center/tile-artwork.svg?rich-sprite";
config.plugins.unshift({
  name: "re-gear-command-center-rich-tiles",
  resolveId(source) {
    return source.replaceAll("\\", "/").endsWith(richTileSpriteImport) ? "\0re-gear-command-center-rich-tiles" : null;
  },
  load(id) {
    if (id !== "\0re-gear-command-center-rich-tiles") return null;
    const tileArtwork = readFileSync(new URL("./assets/command-center/tile-artwork.svg", import.meta.url), "utf8");
    const buttonArtwork = readFileSync(new URL("./assets/command-center/button-artwork.svg", import.meta.url), "utf8");
    const bundledSprite = composeCommandCenterArtwork(tileArtwork, buttonArtwork);
    return `export default ${JSON.stringify(bundledSprite)};`;
  },
});
const offlineBadgeNames = new Set(["offline-ready", "offline-attention", "offline-verify", "offline-required", "offline-ready-gear", "offline-attention-gear", "offline-verify-gear", "offline-required-gear", "offline-ready-compact", "offline-attention-compact", "offline-verify-compact"]);
config.plugins.unshift({
  name: "re-gear-offline-badges",
  resolveId(source) {
    const match = /^\.\/assets\/offline-readiness\/(offline-[a-z-]+)\.svg$/.exec(source);
    return match && offlineBadgeNames.has(match[1]) ? `\0re-gear-badge:${match[1]}` : null;
  },
  load(id) {
    const prefix = "\0re-gear-badge:";
    if (!id.startsWith(prefix)) return null;
    const name = id.slice(prefix.length);
    if (!offlineBadgeNames.has(name)) return null;
    const path = new URL(`./src/assets/offline-readiness/${name}.svg`, import.meta.url);
    return `export default ${JSON.stringify("data:image/svg+xml;base64," + readFileSync(path).toString("base64"))};`;
  },
});
// Bundle the approved compact UI artwork locally; no network or plugin-path dependency.
const uiAssetNames = new Set([
  "regear-header-logo",
  "regear-icon",
  "mode-handheld",
  "mode-tv",
]);
config.plugins.unshift({
  name: "re-gear-ui-assets",
  resolveId(source) {
    const match = /^\.\/assets\/(regear-[a-z-]+|mode-[a-z-]+)\.svg$/.exec(source);
    return match && uiAssetNames.has(match[1]) ? `\0re-gear-ui-asset:${match[1]}` : null;
  },
  load(id) {
    const prefix = "\0re-gear-ui-asset:";
    if (!id.startsWith(prefix)) return null;
    const name = id.slice(prefix.length);
    if (!uiAssetNames.has(name)) return null;
    const path = new URL(`./src/assets/${name}.svg`, import.meta.url);
    return `export default ${JSON.stringify("data:image/svg+xml;base64," + readFileSync(path).toString("base64"))};`;
  },
});
const deckySourcemapPathTransform = config.output.sourcemapPathTransform;

// @decky/rollup expects POSIX separators when it rewrites source paths to
// decky:// URLs. Rollup supplies native backslashes on Windows, which made the
// committed source map differ from the one rebuilt by Linux CI.
config.output.sourcemapPathTransform = (relativeSourcePath, sourcemapPath) =>
  deckySourcemapPathTransform(
    relativeSourcePath.replaceAll("\\", "/"),
    sourcemapPath,
  );

export default config;
