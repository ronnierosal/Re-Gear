import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const icons=readFileSync(new URL('../src/quick-access/command-center-icons.tsx',import.meta.url),'utf8');

const required=[
  'profile','refresh-rate','dock-mode','connection-link','battery','controller-priority',
  'tv-dock','controller-settings','quick-actions','shortcut','appearance','updates','diagnostics','about',
];

test('module menus have dedicated icon vocabulary instead of generic status fallbacks',()=>{
  for(const id of required){
    assert.match(icons,new RegExp(`\\| \\"${id}\\"`),`missing ${id} from CommandCenterIconId`);
    assert.match(icons,new RegExp(`case \\"${id}\\"`),`missing ${id} renderer`);
  }
});

test('module icon pack stays monochrome/currentColor for shared focus semantics',()=>{
  assert.match(icons,/stroke: \\"currentColor\\"/);
  assert.doesNotMatch(icons,/#[0-9a-fA-F]{3,8}/,'icon geometry must not hard-code UI colors');
});
