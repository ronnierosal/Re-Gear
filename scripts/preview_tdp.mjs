// Render the actual TDP component with sample data and HTML control substitutes.
// This development preview does not connect to Decky or the handheld.
import http from "node:http";
import { readFileSync } from "node:fs";
import ts from "typescript";

const compile = (file) => ts.transpileModule(readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8"), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replaceAll('"./backend"', '"./fixture.js"').replaceAll('"./tdp-ui"', '"./tdp-ui.js"')
  .replaceAll('"./auto-tdp-ui"', '"./auto-tdp-ui.js"').replaceAll('"./auto-tdp-controls"', '"./auto-tdp-controls.js"');
const files = new Map([
  ["/tdp-controls.js", compile("tdp-controls.tsx")],
  ["/tdp-ui.js", compile("tdp-ui.ts")],
  ["/auto-tdp-controls.js", compile("auto-tdp-controls.tsx")],
  ["/auto-tdp-ui.js", compile("auto-tdp-ui.ts")],
  ["/fixture.js", `
let state = {schema_version:1,enabled:false,can_enable:true,ready:false,code:'tdp.disabled',current_watts:15,minimum_watts:7,maximum_watts:30,restore_available:false,recovery_required:false,last_result:null,auto_tdp_available:true};
let scenario='ready', generation=0;
let auto={schema_version:1,can_start:false,enabled:false,running:false,stopping:false,code:'tdp.disabled',activity_code:null,target_fps:null,minimum_watts:null,maximum_watts:null};
export const setScenario=(value)=>{scenario=value;};
const autoCopy=(override)=>({...auto,can_start:!override&&state.ready&&!auto.running&&scenario!=='missing',code:override||(scenario==='missing'?'auto_tdp.configuration_missing':state.ready?'auto_tdp.ready':'tdp.disabled')});
export const getAutoTdpStatus=async()=>scenario==='malformed'?{}:autoCopy();
export const startAutoTdp=async(target_fps,minimum_watts,maximum_watts)=>{const token=generation;if(scenario==='slow')await new Promise(resolve=>setTimeout(resolve,1800));if(token!==generation)return autoCopy();auto={...auto,enabled:true,running:true,target_fps,minimum_watts,maximum_watts,activity_code:'auto_tdp.context_settling'};return autoCopy();};
export const stopAutoTdp=async()=>{generation++;auto={...auto,enabled:false,running:false,stopping:false,activity_code:'auto_tdp.stopped'};return autoCopy('auto_tdp.stopped');};
const copy = () => JSON.parse(JSON.stringify(state));
export const getTdpStatus = async () => copy();
export const setTdpEnabled = async (enabled) => { state.enabled=enabled; state.ready=enabled; state.code=enabled?'tdp.ready':'tdp.disabled'; if(!enabled){await stopAutoTdp();if(state.restore_available)await restoreTdpLimit();} return copy(); };
export const applyTdpLimit = async (watts) => { await stopAutoTdp();state.current_watts=watts; state.restore_available=true; state.last_result={state:'applied',code:'tdp.readback_verified',requested_watts:watts,observed_watts:watts}; return copy(); };
export const restoreTdpLimit = async () => { await stopAutoTdp();state.current_watts=15; state.restore_available=false; state.last_result={state:'restored',code:'tdp.readback_verified',requested_watts:15,observed_watts:15}; return copy(); };
`],
  ["/decky-ui.js", `
import React from 'react';
const h=React.createElement;
export const PanelSection=({title,children})=>h('section',null,h('h2',null,title),children);
export const PanelSectionRow=({children})=>h('div',{className:'row'},children);
export const ButtonItem=({children,onClick,disabled})=>h('button',{onClick,disabled},children);
export const ToggleField=({label,checked,disabled,onChange})=>h('label',{className:'row toggle'},label,h('input',{type:'checkbox',checked,disabled,onChange:e=>onChange(e.target.checked)}));
export const DropdownItem=({label,rgOptions,selectedOption,disabled,onChange})=>h('label',{className:'row select'},label,h('select',{value:selectedOption??'',disabled,onChange:e=>onChange({data:Number(e.target.value)})},rgOptions.map(o=>h('option',{key:o.data,value:o.data},o.label))));
`],
  ["/", `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Re-Gear TDP component preview</title>
<script type="importmap">{"imports":{"react":"https://esm.sh/react@19.2.0","react/jsx-runtime":"https://esm.sh/react@19.2.0/jsx-runtime","react-dom/client":"https://esm.sh/react-dom@19.2.0/client?external=react","@decky/ui":"/decky-ui.js"}}</script>
<style>body{margin:0;background:#10151c;color:#e9eef5;font:15px system-ui}main{width:360px;max-width:100%;margin:28px auto}aside{font-size:12px;color:#9eabb8;line-height:1.4;padding:0 14px}section{padding:16px;background:#1a222c;border-radius:10px;margin-top:14px}h1{font-size:20px;margin:0 14px 10px}h2{font-size:17px;margin:0 0 14px}.row{margin:12px 0;line-height:1.45}button{width:100%;background:#33475c;color:#fff;border:0;border-radius:5px;padding:11px 8px;font:inherit}button:disabled,select:disabled{opacity:.4}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #78caff;outline-offset:3px}.toggle,.select{display:flex;justify-content:space-between;align-items:center;gap:12px}select{padding:8px;background:#293b4d;color:white;font:inherit}input{width:20px;height:20px}</style></head><body><main><h1>Re-Gear</h1><aside>Development fixture: sample data and HTML controls.<br>No device connection or hardware actions.</aside><div id="root"></div></main>
<script type="module">import React from 'react';import{createRoot}from'react-dom/client';import{TdpControls}from'/tdp-controls.js';createRoot(document.getElementById('root')).render(React.createElement(TdpControls,{visible:true}));</script></body></html>`],
]);
const server = http.createServer((request, response) => {
  const source = files.get(request.url);
  if (source === undefined) { response.writeHead(404); response.end(); return; }
  response.writeHead(200, { "Content-Type": request.url === "/" ? "text/html; charset=utf-8" : "text/javascript; charset=utf-8", "Cache-Control": "no-store" });
  response.end(request.url === "/" ? source.replace("</aside>", `</aside><aside><label>Fixture scenario <select id="scenario"><option value="ready">Ready</option><option value="missing">Missing configuration</option><option value="malformed">Malformed status</option><option value="slow">Slow start</option></select></label></aside>`)
    .replace("</body>", `<script type="module">import{setScenario}from'/fixture.js';document.getElementById('scenario').addEventListener('change',event=>setScenario(event.target.value));</script></body>`) : source);
});
server.listen(0, "127.0.0.1", () => console.log(`TDP preview: http://127.0.0.1:${server.address().port}`));
