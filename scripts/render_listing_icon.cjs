// Optional authoring tool: install @resvg/resvg-js@2.6.2 in a disposable directory,
// then pass its absolute package path as the sole argument. No runtime dependency.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const renderer = path.resolve(process.argv[2] || '');
if (require(path.join(renderer, 'package.json')).version !== '2.6.2') {
  throw new Error('Use @resvg/resvg-js version 2.6.2');
}
const { Resvg } = require(renderer);
const root = path.resolve(__dirname, '..');
const source = 'src/assets/regear-icon.svg';
const output = 'docs/images/re-gear-listing-icon.png';
const svg = fs.readFileSync(path.join(root, source), 'utf8').replace(/\r\n/g, '\n');
const png = new Resvg(svg, { fitTo: { mode: 'width', value: 512 }, font: { loadSystemFonts: false } }).render().asPng();
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
fs.writeFileSync(path.join(root, output), png);
fs.writeFileSync(path.join(root, 'docs/images/re-gear-listing-icon.json'), JSON.stringify({
  source, source_sha256_lf: hash(svg), output, output_sha256: hash(png),
  renderer: '@resvg/resvg-js@2.6.2', width: 512, height: 512,
}, null, 2) + '\n');
console.log(`${output} ${hash(png)}`);
