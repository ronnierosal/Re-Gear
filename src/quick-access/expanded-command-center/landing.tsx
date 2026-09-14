import {useState,type ReactNode} from "react";
import { DialogButton,Focusable,Navigation,PanelSection,PanelSectionRow } from "@decky/ui";
import { version } from "../../../package.json";
import {projectDocuments,noticesUrl,licenseUrl} from '../../project-credits';

function CreditSection({title,body}:{title:string;body:string}){
  const [open,setOpen]=useState(false);
  return <div><DialogButton aria-expanded={open} onClick={()=>setOpen(value=>!value)}>{title}</DialogButton>{open&&<pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',font:'inherit'}}>{body}</pre>}</div>;
}
export function ReGearAbout(){
  return <Focusable flow-children="vertical" noFocusRing>
    <p>Re-Gear {version}</p>
    <p>{projectDocuments.copyright}</p>
    <DialogButton onClick={()=>Navigation.NavigateToExternalWeb(licenseUrl)}>{projectDocuments.licenseId||'Project license'}</DialogButton>
    {projectDocuments.sections.map((section,index)=><CreditSection key={index} title={section.title} body={section.body}/>)}
    <CreditSection title="Full project license" body={projectDocuments.licenseText}/>
    <DialogButton onClick={()=>Navigation.NavigateToExternalWeb(noticesUrl)}>Third-party notices and licenses</DialogButton>
  </Focusable>;
}
export function ReGearLanding({shortcut}:{shortcut:ReactNode}){
  return <>
    <PanelSection><PanelSectionRow>{shortcut}</PanelSectionRow></PanelSection>
    <PanelSection title="How to use"><PanelSectionRow>
      <ReGearHelp/>
    </PanelSectionRow></PanelSection>
    <PanelSection title="About & credits"><PanelSectionRow><ReGearAbout/></PanelSectionRow></PanelSection>
  </>;
}

export function ReGearHelp(){return <>
      <p>Use your shortcut to open Re-Gear. LB/RB changes tabs; the D-pad moves focus; A selects; B goes back or closes.</p>
      <p>On Quick Access, tap Y to change a button. Hold Y to move cards. Y on an empty slot adds a button; Remove leaves that slot empty. Select a brightness or volume slider with A, then use Up/Down.</p>
</>;}
