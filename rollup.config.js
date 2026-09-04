import deckyPlugin from "@decky/rollup";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const config = deckyPlugin({});
// Bundle the approved artwork locally; no network or plugin-path dependency.
const brandImagePath = fileURLToPath(new URL("./docs/images/re-gear-decky-monochrome.jpg", import.meta.url));
config.plugins.unshift({
  name: "re-gear-brand-image",
  resolveId(source) {
    if (source === "../docs/images/re-gear-decky-monochrome.jpg") return "\0re-gear-brand-image";
    return null;
  },
  load(id) {
    if (id !== "\0re-gear-brand-image") return null;
    return `export default ${JSON.stringify("data:image/jpeg;base64," + readFileSync(brandImagePath).toString("base64"))};`;
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
