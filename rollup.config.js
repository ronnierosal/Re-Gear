import deckyPlugin from "@decky/rollup";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const config = deckyPlugin({});
const offlineBadgeNames = new Set(["offline-ready", "offline-attention", "offline-verify", "offline-required"]);
config.plugins.unshift({
  name: "re-gear-offline-badges",
  resolveId(source) {
    const match = /^\.\/assets\/offline-readiness\/(offline-[a-z]+)\.svg$/.exec(source);
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
// Bundle the approved artwork locally; no network or plugin-path dependency.
const brandImagePath = fileURLToPath(new URL("./docs/images/re-gear-decky-white-transparent.png", import.meta.url));
config.plugins.unshift({
  name: "re-gear-brand-image",
  resolveId(source) {
    if (source === "../docs/images/re-gear-decky-white-transparent.png") return "\0re-gear-brand-image";
    return null;
  },
  load(id) {
    if (id !== "\0re-gear-brand-image") return null;
    return `export default ${JSON.stringify("data:image/png;base64," + readFileSync(brandImagePath).toString("base64"))};`;
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
