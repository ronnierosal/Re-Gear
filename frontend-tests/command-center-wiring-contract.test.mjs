import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import ts from "typescript";

const modelUrl = new URL("../src/quick-access/expanded-command-center/model.ts", import.meta.url);
const modelJs = ts.transpileModule(readFileSync(modelUrl, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { sampleTiles } = await import(`data:text/javascript;base64,${Buffer.from(modelJs).toString("base64")}`);

const approved = Object.fromEntries(
  Object.entries(sampleTiles).map(([tab, tiles]) => [tab, tiles.map(tile => tile.id)]),
);

const tileSourceUrl = new URL("../src/quick-access/expanded-command-center/tile-source.ts", import.meta.url);

/**
 * Integration guard for the wiring workstream.
 *
 * The UI owns tab composition and stable tile IDs. A live source may change
 * values, tones and detail text, but it must not shrink/reorder the approved
 * menu or reintroduce an older composition. This test is intentionally dormant
 * on the UI-only branch and becomes active as soon as tile-source.ts is present
 * in an integration tree.
 */
test("live Command Center source preserves the approved UI tile contract", {
  skip: !existsSync(tileSourceUrl),
}, async () => {
  const graph=[
    'quick-access/performance-state', 'quick-access/expanded-command-center/model',
    'quick-access/expanded-command-center/tiles', 'quick-access/expanded-command-center/tile-source',
  ].map(path=>ts.transpileModule(readFileSync(new URL(`../src/${path}.ts`,import.meta.url),'utf8'),{
    compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020},
  }).outputText.replace(/^import[^;]*;$/gm,'')).join('\n');
  const {buildTiles}=await import(`data:text/javascript;base64,${Buffer.from(graph).toString('base64')}`);
  for(const readings of [{},{fresh:false,performanceFresh:false},{fresh:true,performanceFresh:true}]){
    const view=buildTiles(readings);
    for(const [tab,ids] of Object.entries(approved))
      assert.deepEqual(view[tab].map(tile=>tile.id),ids,`${tab} composition must remain stable`);
    assert.equal(view.quick.find(tile=>tile.id==='disconnect').wide,true);
  }
});
