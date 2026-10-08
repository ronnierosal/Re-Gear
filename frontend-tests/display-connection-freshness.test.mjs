import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const compile = source => ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText;
const module = await import('data:text/javascript;base64,' + Buffer.from(compile(readFileSync(new URL('../src/quick-access/expanded-command-center/runtime-detail-source.ts',import.meta.url),'utf8'))).toString('base64'));
const fixture = () => ({snapshot:{schema_version:3,observed_at:'2026-10-08T00:00:00.000Z',support_tier:'certified',gpus:[{role:'internal',present:true,confidence:'verified'},{role:'external',present:true,confidence:'verified'}],egpu_link:{applicable:true,state:'up',confidence:'observed',error:'',speed_gtps:8,width_lanes:4}},diagnostics:{hardware_profiles:{schema_version:1,egpu:{status:'exact'}}}});
const evidence = (value,fresh=true) => {assert.equal(typeof module.egpuConnectionEvidence,'function');return module.egpuConnectionEvidence(value,fresh);};

test('same-snapshot verified attachment and observed healthy link compose connection only',()=>{
 const p=fixture();assert.equal(evidence(p),true);
 p.snapshot.egpu_link.confidence='verified';assert.equal(evidence(p),true);
 p.snapshot.gpus[1].selected_for_render=false;p.inference={mode:'portable'};
 assert.equal(evidence(p),true,'renderer and destination do not supply connection evidence');
});
test('standalone observed link, malformed, ambiguous and denied facts stay Unknown',()=>{
 const mutations=[p=>p.snapshot.schema_version=2,p=>p.snapshot.gpus[0].confidence='unknown',p=>p.snapshot.gpus[0].present='true',p=>delete p.diagnostics,p=>p.diagnostics.hardware_profiles.egpu.status='unknown',p=>p.diagnostics.hardware_profiles.schema_version=2,p=>p.snapshot.support_tier='unknown',p=>p.snapshot.gpus[1].confidence='observed',p=>p.snapshot.gpus.push({...p.snapshot.gpus[1]}),p=>p.snapshot.gpus.push({role:'unknown',present:true,confidence:'verified'}),p=>p.snapshot.egpu_link.applicable=1,p=>p.snapshot.egpu_link.error='read denied',p=>delete p.snapshot.egpu_link.error,p=>p.snapshot.egpu_link.confidence='unknown',p=>p.snapshot.egpu_link.speed_gtps=Infinity,p=>p.snapshot.egpu_link.speed_gtps=0,p=>p.snapshot.egpu_link.width_lanes=1.5,p=>p.snapshot.egpu_link.width_lanes='4',p=>p.snapshot.gpus[1].present='true'];
 for(const mutate of mutations){const p=fixture();mutate(p);assert.equal(evidence(p),null);}
 for(const p of [null,{},[],Object.assign(Object.create(fixture()),{})])assert.equal(evidence(p),null);
 const p=fixture();Object.defineProperty(p.snapshot.egpu_link,'error',{get(){throw new Error('must not read accessor');}});assert.equal(evidence(p),null);
 assert.equal(evidence(fixture(),false),null);assert.equal(evidence(fixture(),'true'),null);
});
test('link down is not physical cable absence; observed down and absent GPU stay Unknown',()=>{
 const p=fixture();p.snapshot.egpu_link.state='down';assert.equal(evidence(p),null);
 p.snapshot.egpu_link.confidence='verified';assert.equal(evidence(p),false);
 p.snapshot.egpu_link.error='unavailable';assert.equal(evidence(p),null);
 const absent=fixture();absent.snapshot.gpus.pop();absent.snapshot.egpu_link={applicable:false,state:'unknown',confidence:'verified',error:''};assert.equal(evidence(absent),null);
});

// Extract the actual Content freshness expressions, displayAction publication
// and existing expiry effect. No reimplementation of the production timer.
function contentHarness(payload=fixture()){
 const source=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
 const tree=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const content=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='Content');
 const variables=new Map();let display,expiry;
 function visit(n){
  if(ts.isVariableDeclaration(n))variables.set(n.name.getText(tree),n.initializer);
  if(ts.isCallExpression(n)&&n.expression.getText(tree)==='useEffect'){
   const body=n.arguments[0]?.getText(tree)||'';
   if(body.includes('runtimeDetails.publish(')){
    function find(v){if(ts.isPropertyAssignment(v)&&v.name.getText(tree)==='displayAction')display=v.initializer;ts.forEachChild(v,find);}find(n.arguments[0]);
   }
   if(body.includes('setMenuAgeTick')&&body.includes('menuObservation.remainingMs'))expiry=n.arguments[0];
  }
  ts.forEachChild(n,visit);
 }visit(content);assert.ok(display&&expiry);
 const tileSource=compile(readFileSync(new URL('../src/quick-access/expanded-command-center/tile-source.ts',import.meta.url),'utf8')).replace(/^import[^;]*;$/gm,'').replace(/export /g,'');
 const observationAge=new Function(tileSource+';return observationAge;')();
 let now=Date.parse(payload.snapshot.observed_at),tick=0,timer=null,rpc=0;
 const env={payload,loading:false,error:'',READABLE_SNAPSHOT_SCHEMA:3,SNAPSHOT_STALE_AFTER_MS:10000,Date:{now:()=>now},observationAge,
  primaryDisplayAction:{target:'tv',disabled:false,description:'Existing guarded route'},runtimeOwner:{stopped:false},activateDisplay:()=>{rpc++;},egpuConnectionEvidence:module.egpuConnectionEvidence,
  window:{setTimeout(callback,ms){timer={callback,at:now+ms};return timer;},clearTimeout(){timer=null;}},setMenuAgeTick:update=>{tick=update(tick);},menuAgeTick:tick};
 function run(node){const js=compile('const extracted = '+node.getText(tree)+';');return new Function(...Object.keys(env),js+';return extracted;')(...Object.values(env));}
 function render(){for(const name of ['menuObservation','menuSchemaReadable','menuFresh'])env[name]=run(variables.get(name));const action=run(display);run(expiry)();return action;}
 return {env,render,advance(ms){now+=ms;if(timer&&timer.at<=now){const cb=timer.callback;timer=null;cb();}},rpc:()=>rpc,tick:()=>tick};
}
test('actual Content publishes the fact without changing destination, availability or callback',()=>{
 const h=contentHarness();const action=h.render();assert.equal(action.egpuConnected,true);assert.equal(action.target,'tv');assert.equal(action.available,true);assert.equal(action.reason,'Existing guarded route');assert.equal(h.rpc(),0);
 h.env.primaryDisplayAction.disabled=true;assert.equal(h.render().egpuConnected,true);assert.equal(h.render().available,false);
 h.env.primaryDisplayAction.target='ally';assert.equal(h.render().target,'ally');assert.equal(h.render().egpuConnected,true);
});
test('actual existing ten-second expiry withdraws mark without another RPC',()=>{
 const h=contentHarness();assert.equal(h.render().egpuConnected,true);h.advance(9999);assert.equal(h.render().egpuConnected,true);h.advance(1);assert.equal(h.tick(),1);assert.equal(h.render().egpuConnected,null);assert.equal(h.render().target,null);assert.equal(h.rpc(),0);
});
test('actual Content loading, failure, unreadable schema and future timestamp withdraw cached marking',()=>{
 for(const change of [h=>h.env.loading=true,h=>h.env.error='unavailable',h=>h.env.payload.snapshot.schema_version=2,h=>h.env.payload.snapshot.observed_at='2099-01-01T00:00:00Z']){
  const h=contentHarness();assert.equal(h.render().egpuConnected,true);change(h);assert.equal(h.render().egpuConnected,null);assert.equal(h.rpc(),0);
 }
});
