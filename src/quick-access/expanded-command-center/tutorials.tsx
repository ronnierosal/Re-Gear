import {useEffect,useRef,useState} from 'react';
import {DialogButton,Focusable,Navigation} from '@decky/ui';

const guide='https://github.com/ronnierosal/Re-Gear/wiki/';
/** Condensed from docs/wiki/player/tutorial-cards.md; labels match this build. */
export const tutorials=[
 {id:'first-connect',title:'First Connection',source:guide+'eGPU-and-Docking#first-connection',steps:[
  'Follow the instructions for your installed build and test setup.',
  'Connect the dock, read the connection and display messages, and wait for the transition to finish.',
  'Check picture, audio and controls. A TV picture alone does not tell you which graphics device a game uses.',
 ]},
 {id:'disconnect',title:'Safe Disconnect',source:guide+'eGPU-and-Docking#safe-disconnect',steps:[
  'Follow your build’s instructions about games and connected storage.',
  'Select Safe Disconnect once, read the result, and verify handheld picture, audio and controls return.',
  'Physical unplugging needs separate clearance for your exact supervised setup. A software result alone is not enough.',
 ]},
 {id:'sleep-wake',title:'Sleep & Wake',source:guide+'eGPU-and-Docking#sleep-and-wake',steps:[
  'Sleep with an eGPU is still being validated.',
  'Sleeping with the eGPU connected and disconnecting before sleep are separate choices in the design. Your build may not support them.',
  'If sleep is blocked, do not force it or use software reconnect.',
 ]},
 {id:'stuck',title:'If You Get Stuck',source:guide+'Troubleshooting',steps:[
  'Stop repeating the action. Note your version, the message, what you expected and what happened.',
  'Include which screen you used and whether a game was running.',
  'Open Settings → Diagnostics for available help. Review a support preview before sharing it.',
 ]},
] as const;

export function Tutorials(){
 const [selected,setSelected]=useState<string|null>(null);
 const restore=useRef<string>(tutorials[0].id);
 const root=useRef<HTMLDivElement>(null);
 const topic=tutorials.find(item=>item.id===selected);
 useEffect(()=>{root.current?.querySelector<HTMLElement>(selected?'[data-tutorial-back]':`[data-tutorial="${restore.current}"]`)?.focus();},[selected]);
 const back=()=>setSelected(null);
 return <div ref={root}><Focusable flow-children="vertical" noFocusRing {...(topic?{onCancelButton:(event:CustomEvent)=>{event.preventDefault();event.stopPropagation();back();}}:{})}>
  {topic?<><DialogButton preferredFocus data-tutorial-back onClick={back}>Back to tutorials</DialogButton><h3>{topic.title}</h3><ol>{topic.steps.map(step=><li key={step}>{step}</li>)}</ol><DialogButton onClick={()=>Navigation.NavigateToExternalWeb(topic.source)}>Read the guide</DialogButton></>:<Focusable className="rg-expanded-grid" flow-children="grid" noFocusRing style={{gridTemplateColumns:'repeat(2,minmax(0,1fr))'}}>{tutorials.map(item=><DialogButton key={item.id} preferredFocus={item.id===restore.current} data-tutorial={item.id} className="rg-expanded-tile" onClick={()=>{restore.current=item.id;setSelected(item.id);}}>{item.title}</DialogButton>)}</Focusable>}
 </Focusable></div>;
}
