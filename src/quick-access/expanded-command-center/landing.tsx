import type { ReactNode } from "react";
import { PanelSection,PanelSectionRow } from "@decky/ui";
import { version,license } from "../../../package.json";
import {projectCredits,noticesUrl} from '../../project-credits';

export function ReGearAbout(){
  return <>
    <p>Re-Gear {version} · Ronnie Rosal</p>
    <ul>{projectCredits.map(credit=><li key={credit.project}><a href={credit.source}>{credit.project}</a> — {credit.attribution}</li>)}</ul>
    <p><a href={noticesUrl}>Third-party notices and licenses</a></p>
  </>;
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
