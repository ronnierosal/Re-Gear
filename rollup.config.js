import deckyPlugin from "@decky/rollup";
import { readFileSync } from "node:fs";

const config = deckyPlugin({});
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
