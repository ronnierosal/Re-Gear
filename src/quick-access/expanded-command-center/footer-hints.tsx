import type { Tab } from "./model";

export type CommandCenterEditMode = "normal" | "customize" | "move" | "quick-actions";

export type FooterHint = {
  button: "LB" | "RB" | "A" | "B" | "X" | "Y";
  label: string;
  hold?: boolean;
};

/**
 * Presentation-only button legend. The shell/runtime owns actual controller
 * events; this keeps visible prompts consistent with the approved interaction
 * contract and prevents wiring lanes from inventing different labels.
 */
export function footerHintsFor(tab: Tab, nested: boolean, mode: CommandCenterEditMode = "normal",context:"main"|"left"|"right"="main"): readonly FooterHint[] {
  if (mode === "move") return [
    { button: "A", label: "Place" },
    { button: "B", label: "Cancel" },
  ];
  if (mode === "customize") return [
    { button: "A", label: "Choose" },
    { button: "B", label: "Cancel" },
  ];
  if (mode === "quick-actions") return [
    { button: "A", label: "Choose" },
    { button: "B", label: "Cancel" },
  ];
  if (nested) return [
    { button: "A", label: "Select" },
    { button: "B", label: "Back" },
  ];

  const base: FooterHint[] = [
    { button: "LB", label: "Tab" },
    { button: "RB", label: "Tab" },
    { button: "A", label: "Select" },
    { button: "B", label: "Close" },
  ];

  if(context==="left")return base;
  if(context==="right"){if(tab==="quick")base.splice(2,0,{button:"Y",label:"Customize"});return base;}
  if (tab === "quick") {
    base.splice(2, 0,
      { button: "Y", label: "Customize" },
      { button: "Y", label: "Move", hold: true },
    );
  } else {
    base.splice(2, 0, { button: "Y", label: "Move", hold: true });
  }
  return base;
}

export function CommandCenterFooterHints({ tab, nested = false, mode = "normal",context="main" }: {
  tab: Tab;
  nested?: boolean;
  mode?: CommandCenterEditMode;
  context?:"main"|"left"|"right";
}) {
  return <>
    {footerHintsFor(tab, nested, mode,context).map((hint, index) =>
      <span key={`${hint.button}-${hint.label}-${index}`} data-footer-hint data-button={hint.button} data-hold={hint.hold ? "true" : undefined}>
        {hint.hold && <small>Hold </small>}<kbd className={hint.button.length === 1 ? "rg-expanded-round" : undefined}>{hint.button}</kbd> {hint.label}
      </span>
    )}
  </>;
}
