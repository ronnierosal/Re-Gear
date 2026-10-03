import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.REGEAR_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const produced = JSON.parse(execFileSync(python, ['tests/issued_presentation_result.py'],
  { cwd: root, encoding: 'utf8', maxBuffer: 1024 * 1024 }));
const source = readFileSync(new URL('../src/transition-acknowledgement-control.tsx', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
}}).outputText;
const imports = {
  'react/jsx-runtime': {}, react: {}, '@decky/ui': {}, './backend': {},
  './regear-theme': { regearTheme: {} },
};
const exports = {};
new Function('exports', 'require', code)(exports, name => imports[name]);

test('actual shared control offers the ID issued by real preview/execute and both production RPC reads', () => {
  assert.equal(produced.operation_id.length, 24);
  assert.equal(produced.journal.acknowledgement_id, produced.operation_id);
  assert.equal(produced.status.acknowledgement_id, produced.operation_id);
  assert.equal(exports.displayAcknowledgementId(produced.journal, produced.status), produced.operation_id);
});

test('real-issued result still requires matching durable owner and fresh two-view identity', () => {
  for (const journal of [
    { ...produced.journal, owner: 'sleep' },
    { ...produced.journal, code: 'transition.running' },
    { ...produced.journal, durable: false },
    { ...produced.journal, acknowledgement_id: produced.operation_id + '/' },
  ]) assert.equal(exports.displayAcknowledgementId(journal, produced.status), '');
  assert.equal(exports.displayAcknowledgementId(produced.journal,
    { ...produced.status, acknowledgement_id:
      (produced.operation_id[0] === 'a' ? 'b' : 'a') + produced.operation_id.slice(1) }), '');
});
