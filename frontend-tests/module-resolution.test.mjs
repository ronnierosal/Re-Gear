import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync } from "node:fs";

const SRC = new URL("../src/", import.meta.url);

test("no two source modules share a basename", () => {
  // TypeScript resolves ./name to name.ts before name.tsx, so a pure module
  // and a renderer sharing a basename makes the renderer unreachable by any
  // import — and nothing catches it until the first caller arrives, because
  // an unimported file still typechecks. quick-access-nav.ts/.tsx shipped
  // exactly that; the repo's pattern is distinct basenames, as in
  // quick-access-sections.ts / quick-access-overview.tsx.
  const seen = new Map();
  const collisions = [];
  for (const entry of readdirSync(SRC, { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const match = /^(.*)\.(ts|tsx)$/.exec(entry.name);
    if (!match || entry.name.endsWith(".d.ts")) continue;
    const [, base] = match;
    if (seen.has(base)) collisions.push(`${seen.get(base)} and ${entry.name}`);
    else seen.set(base, entry.name);
  }
  assert.deepEqual(collisions, [], `shadowed modules: ${collisions.join("; ")}`);
});
