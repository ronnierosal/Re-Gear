import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/transition-acknowledgement-control.tsx',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
const ID='DJ-6XJcMH8MAbHu6uZmX9SIp';
const journal={schema_version:1,code:'transition.blocked',owner:'presentation',acknowledgement_required:true,action_required:true,acknowledgement_id:ID,durable:true};
const status={schema_version:1,code:'transition.blocked',acknowledgement_required:true,action_required:true,acknowledgement_id:ID,durable:true,target:'portable'};
const settle=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
function nodes(tree){return !tree||typeof tree!=='object'?[]:Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];}
function harness(j=journal,s=status){
  const h={journal:j,status:s,acks:[],effects:[],cleanups:[],timers:new Map(),next:0};let slots=[],index=0;
  const useState=value=>{const slot=index++;if(!(slot in slots))slots[slot]=value;return[slots[slot],next=>{slots[slot]=typeof next==='function'?next(slots[slot]):next;}];};
  const useRef=value=>{const slot=index++;if(!(slot in slots))slots[slot]={current:value};return slots[slot];};
  const useEffect=fn=>{const slot=index++;if(!(slot in slots)){slots[slot]=true;h.effects.push(fn);}};
  const jsx=(type,props)=>({type,props});
  const imports={
    'react/jsx-runtime':{jsx,jsxs:jsx},react:{useEffect,useRef,useState},'@decky/ui':{DialogButton:'button'},
    './backend':{
      getTransitionJournalStatus:()=>h.readJournal(),getSupervisedTvSwitchStatus:()=>h.readStatus(),
      acknowledgeSupervisedTvSwitch:async id=>{h.acks.push(id);return{schema_version:1,acknowledged:true};},
    },'./regear-theme':{regearTheme:{border:'#345',accentSoft:'#8df',muted:'#abc'}},
  };
  const exports={};new Function('exports','require',code)(exports,name=>imports[name]);
  h.readJournal=async()=>h.journal;h.readStatus=async()=>h.status;
  h.render=()=>{index=0;return exports.TransitionAcknowledgementControl();};
  h.mount=async()=>{h.render();for(const effect of h.effects.splice(0))h.cleanups.push(effect());await settle();return h.render();};
  h.unmount=()=>h.cleanups.splice(0).forEach(cleanup=>cleanup?.());
  const originalSetTimeout=global.setTimeout,originalClearTimeout=global.clearTimeout;
  global.setTimeout=fn=>{const id=++h.next;h.timers.set(id,fn);return id;};global.clearTimeout=id=>h.timers.delete(id);
  h.restore=()=>{global.setTimeout=originalSetTimeout;global.clearTimeout=originalClearTimeout;};return h;
}

test('exact owner result exposes one accessible action and rechecks before acknowledgement',async()=>{
  const h=harness();try{
    const tree=await h.mount();const button=nodes(tree).find(node=>node.type==='button');
    assert.match(String(button.props.children),/Acknowledge prior display result/);
    button.props.onClick();button.props.onClick();await settle();
    assert.deepEqual(h.acks,[ID]);
    assert.match(JSON.stringify(h.render()),/Prior display result acknowledged/);
  }finally{h.restore();}
});

test('unmount during the freshness recheck cannot acknowledge or publish a late result',async()=>{
  const h=harness();try{
    const tree=await h.mount();const button=nodes(tree).find(node=>node.type==='button');
    let resolveJournal;h.readJournal=()=>new Promise(resolve=>{resolveJournal=resolve;});
    button.props.onClick();h.unmount();resolveJournal(journal);await settle();
    assert.deepEqual(h.acks,[]);
  }finally{h.restore();}
});

test('wrong owner, changed identity, and active operation fail closed without dispatch',async()=>{
  for(const [j,s] of [[{...journal,owner:'sleep'},status],[journal,{...status,code:'transition.running'}],[journal,{...status,acknowledgement_id:'DJ-other-result-123456'}]]){
    const h=harness(j,s);try{assert.equal(await h.mount(),null);assert.deepEqual(h.acks,[]);}finally{h.restore();}
  }
  const h=harness();try{
    const tree=await h.mount();const button=nodes(tree).find(node=>node.type==='button');
    h.status={...status,acknowledgement_id:'DJ-changed-result-123456'};
    button.props.onClick();await settle();assert.deepEqual(h.acks,[]);
    assert.match(JSON.stringify(h.render()),/Display result changed/);
  }finally{h.restore();}
});
